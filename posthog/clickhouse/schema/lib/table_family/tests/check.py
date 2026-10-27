#!/usr/bin/env python3
"""Run table-family checks against a local ClickHouse and Keeper."""

import os
import sys
import json
import base64
import shutil
import socket
import tempfile
import subprocess
import urllib.request
from pathlib import Path
from uuid import uuid4


def check() -> None:
    host = os.environ.get("CLICKHOUSE_HOST", "localhost")
    if socket.gethostbyname(host) != "127.0.0.1":
        raise ValueError("Table-family checks require a local ClickHouse")
    username = os.environ.get("CLICKHOUSE_USER", "default")
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    database = f"table_family_check_{uuid4().hex}"
    tofu = os.environ.get("TOFU", "tofu")
    fixture = Path(__file__).parent / "fixture"
    with tempfile.TemporaryDirectory(prefix="table-family-") as directory:
        root = Path(directory)
        shutil.copyfile(fixture / "main.tf", root / "main.tf")
        shutil.copytree(
            fixture.parent.parent.parent, root / "lib", ignore=shutil.ignore_patterns("tests", ".terraform")
        )
        (root / "main.tf").write_text(
            (root / "main.tf").read_text().replace('source = "../../"', 'source = "./lib/table_family"')
        )
        env = {
            **os.environ,
            "TF_VAR_database": database,
            "TF_VAR_host": host,
            "TF_VAR_username": username,
            "TF_VAR_password": password,
            "TF_DATA_DIR": str(root / ".terraform"),
            "TF_INPUT": "0",
        }

        def run(*arguments: str) -> subprocess.CompletedProcess[str]:
            result = subprocess.run([tofu, f"-chdir={root}", *arguments], env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stdout + result.stderr)
            return result

        def query(sql: str) -> str:
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            request = urllib.request.Request(
                f"http://{host}:8123", data=sql.encode(), headers={"Authorization": f"Basic {token}"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode()

        run("init", "-backend=false", "-no-color")
        try:
            run("apply", "-auto-approve", "-no-color")
            ddl = json.loads(
                query(f"SELECT name, create_table_query FROM system.tables WHERE database = '{database}' FORMAT JSON")
            )["data"]
            objects = {row["name"]: row["create_table_query"] for row in ddl}
            assert set(objects) == {
                "sharded_family",
                "family",
                "writable_family",
                "kafka_family",
                "family_mv",
                "reference",
                "reference_read",
                "plain_reference",
                "writable_reference",
                "kafka_reference",
                "reference_mv",
                "routed_read",
                "routed_write",
            }, objects.keys()
            for name, definition in objects.items():
                if name in {"sharded_family", "reference"}:
                    assert (
                        "INDEX team_id_idx" in definition
                        and "PROJECTION by_team" in definition
                        and "CONSTRAINT positive_team" in definition
                    ), definition
                    assert "CODEC(Delta(8), ZSTD(1))" in definition and "MATERIALIZED value * 2" in definition, (
                        definition
                    )
                else:
                    assert (
                        "INDEX team_id_idx" not in definition
                        and "PROJECTION by_team" not in definition
                        and "CONSTRAINT positive_team" not in definition
                        and "CODEC(" not in definition
                        and "MATERIALIZED value" not in definition
                    ), definition
            assert "doubled" not in objects["writable_family"], objects["writable_family"]
            query(
                f"INSERT INTO {database}.writable_family SETTINGS insert_distributed_sync=1 VALUES (1, '2026-01-01 00:00:00', 10)"
            )
            assert query(f"SELECT doubled FROM {database}.family") == "20\n"
            assert query(f"SELECT doubled FROM {database}.routed_read") == "20\n"
            query(
                f"INSERT INTO {database}.writable_reference SETTINGS insert_distributed_sync=1 VALUES (1, '2026-01-01 00:00:00', 7)"
            )
            assert query(f"SELECT doubled FROM {database}.reference") == "14\n"
            assert query(f"SELECT doubled FROM {database}.reference_read") == "14\n"
            assert "ENGINE = MergeTree" in objects["plain_reference"]
            assert "Kafka(warpstream_ingestion)" in objects["kafka_reference"]
            assert "kafka_topic_list =" in objects["kafka_reference"]
            assert (
                f"kafka_topic_list = 'isolated_{database}_input_test,isolated_{database}_extra_test'"
                in objects["kafka_family"]
            )
            assert f"kafka_topic_list = '{database}_reference_input_test'" in objects["kafka_reference"]
            assert f"TO {database}.reference" in objects["reference_mv"]
            assert f"{database}.sharded_family" in objects["sharded_family"]
            assert f"noshard/{database}.reference" in objects["reference"]
            run("plan", "-no-color", "-out=tfplan")
            plan = json.loads(run("show", "-json", "tfplan").stdout)
            changes = [
                change for change in plan.get("resource_changes", []) if change["change"]["actions"] != ["no-op"]
            ]
            assert not changes, changes
            invalid = subprocess.run(
                [tofu, f"-chdir={root}", "plan", "-no-color", "-var=bad_indexes=true"],
                env=env,
                capture_output=True,
                text=True,
            )
            diagnostic = " ".join((invalid.stdout + invalid.stderr).split())
            assert invalid.returncode != 0 and "only be overridden on a MergeTree storage table" in diagnostic, (
                diagnostic
            )
            sys.stdout.write("PASS: table-family checks and empty second plan\n")
        finally:
            run("destroy", "-auto-approve", "-no-color")


if __name__ == "__main__":
    check()
