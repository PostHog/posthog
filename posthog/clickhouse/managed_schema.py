"""Builds a ClickHouse database from the OpenTofu schema in `posthog/clickhouse/schema`.

For tests and local setup only. Deployed environments apply the schema outside the app.
"""

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from django.conf import settings

from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DATA_BACKFILL_SQL, EXCHANGE_RATE_TABLE_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]

# Tables whose starting rows the app loads: (table name, function that builds the INSERT).
# Reference tables whose rows never change at runtime declare them in the schema instead.
SEED_DATA_TABLES = ((EXCHANGE_RATE_TABLE_NAME, EXCHANGE_RATE_DATA_BACKFILL_SQL),)
DECLARED_DATA_TABLES = ("channel_definition", "web_bot_definition")


class ClickHouseDatabase:
    """The database named by `settings.CLICKHOUSE_DATABASE`."""

    # CREATE statements of every object, as ClickHouse reports them after `apply_schema`.
    _snapshot: ClassVar[dict[str, str]] = {}
    # Reference rows declared by OpenTofu; application rows must not enter fixture snapshots.
    _snapshot_rows: ClassVar[dict[str, list[tuple]]] = {}

    def __init__(self) -> None:
        self.name: str = settings.CLICKHOUSE_DATABASE

    def create(self) -> None:
        self._admin_execute(f"CREATE DATABASE IF NOT EXISTS `{self.name}`")

    def drop(self) -> None:
        # SYNC frees the replication paths, so that the schema can be applied again straight away.
        self._admin_execute(f"DROP DATABASE IF EXISTS `{self.name}` SYNC")

    def is_single_node(self) -> bool:
        """Whether every cluster the server knows points only at the server itself."""
        rows = self._admin_execute(
            "SELECT count() FROM system.clusters WHERE NOT is_local AND NOT startsWith(host_address, '127.')"
        )
        return rows[0][0] == 0

    def apply_schema(self, *, kafka: bool) -> None:
        """Creates every object the schema declares that the database does not have yet."""
        result = self._run_schema_tool("apply", kafka=kafka)
        if result.returncode != 0:
            raise RuntimeError(f"bin/clickhouse-schema apply failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")

    def plan_schema(self, *, kafka: bool) -> tuple[bool, str]:
        """Whether the database differs from the declared schema, and the plan that shows how."""
        result = self._run_schema_tool("plan", "-detailed-exitcode", kafka=kafka)
        # -detailed-exitcode: 0 means no changes, 2 means changes, anything else is an error.
        if result.returncode not in (0, 2):
            raise RuntimeError(f"bin/clickhouse-schema plan failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")
        return result.returncode == 2, result.stdout

    def _run_schema_tool(self, *args: str, kafka: bool) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "CLICKHOUSE_HOST": settings.CLICKHOUSE_HOST,
            "CLICKHOUSE_USER": settings.CLICKHOUSE_USER,
            "CLICKHOUSE_PASSWORD": settings.CLICKHOUSE_PASSWORD,
            "CLICKHOUSE_DATABASE": self.name,
            "CLICKHOUSE_SECURE": "true" if settings.CLICKHOUSE_SECURE else "false",
            "CLICKHOUSE_SCHEMA_KAFKA": "true" if kafka else "false",
            "CLICKHOUSE_SCHEMA_TEST": "true" if settings.TEST else "false",
        }
        if settings.TEST and not settings.IN_EVAL_TESTING:
            # Fixture DROP statements can still own paths after the next pytest process starts.
            env["TF_VAR_keeper_path"] = f"/clickhouse/test/{self.name}/{uuid4().hex}/{{table}}"
        return subprocess.run(
            [str(REPO_ROOT / "bin" / "clickhouse-schema"), *args, "-no-color"],
            env=env,
            capture_output=True,
            text=True,
        )

    def create_test_tables(self, *, kafka: bool) -> None:
        # Fixtures can replace tables and their Keeper paths. Restore the initial schema rather
        # than reconciling those temporary definitions through OpenTofu between test packages.
        if self._snapshot:
            self.restore()
        else:
            # A previous pytest process can leave fixture-specific definitions and Keeper paths.
            if not settings.IN_EVAL_TESTING:
                self.drop()
                self.create()
            self.apply_schema(kafka=kafka)
            self.seed()
            self.snapshot()

    def snapshot(self) -> None:
        """Records the schema and the rows it declares, so that `restore` can rebuild both without running OpenTofu again."""
        rows = sync_execute(
            """SELECT name, create_table_query FROM system.tables
               WHERE database = %(database)s AND name NOT LIKE '.inner%%'
               SETTINGS format_display_secrets_in_show_and_select = 1""",
            {"database": self.name},
        )
        ClickHouseDatabase._snapshot = dict(rows)
        ClickHouseDatabase._snapshot_rows = {
            name: sync_execute(f"SELECT * FROM `{name}`") for name in DECLARED_DATA_TABLES
        }

    @classmethod
    def declares_column(cls, table: str, column: str) -> bool:
        """Whether the schema, as `snapshot` recorded it, has the column in the table."""
        return f"`{column}` " in cls._snapshot.get(table, "")

    def restore(self) -> None:
        """Drops the database and rebuilds the schema and rows `snapshot` recorded."""
        if not self._snapshot:
            raise RuntimeError("ClickHouseDatabase.snapshot() must run before restore()")
        self.drop()
        self.create()

        def run(query: str) -> Exception | None:
            try:
                sync_execute(query)
            except Exception as error:
                return error
            return None

        # Views and materialized views need the objects they read from, so retry what failed until all exist.
        # A fixture's asynchronous DROP can still own the original replica path.
        pending = [
            re.sub(
                r"(ENGINE = Replicated\w*MergeTree\(')[^']*(')",
                rf"\g<1>/clickhouse/test/{self.name}/{uuid4().hex}/{name}\g<2>",
                query,
            )
            for name, query in self._snapshot.items()
        ]
        with ThreadPoolExecutor(max_workers=8) as executor:
            while pending:
                errors = list(executor.map(run, pending))
                failed = [(query, error) for query, error in zip(pending, errors) if error is not None]
                if len(failed) == len(pending):
                    raise failed[0][1]
                pending = [query for query, _ in failed]
        for name, table_rows in self._snapshot_rows.items():
            sync_execute(f"INSERT INTO `{name}` VALUES", table_rows)
        self.seed()

    def seed(self) -> None:
        """Loads the reference data of every seed table that is empty."""
        for table_name, query_fn in SEED_DATA_TABLES:
            if not sync_execute(f"SELECT count() FROM {table_name}")[0][0]:
                sync_execute(query_fn())

    def _admin_execute(self, query: str) -> list[tuple]:
        # The pooled client connects to the database itself, which may not exist yet.
        client = Client(
            host=settings.CLICKHOUSE_HOST,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            secure=settings.CLICKHOUSE_SECURE,
            ca_certs=settings.CLICKHOUSE_CA,
            verify=settings.CLICKHOUSE_VERIFY,
            database="default",
        )
        try:
            return client.execute(query)
        finally:
            client.disconnect()
