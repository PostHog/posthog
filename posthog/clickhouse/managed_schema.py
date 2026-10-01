"""Builds a ClickHouse database from the OpenTofu schema in `posthog/clickhouse/schema`.

For tests and local setup only. Deployed environments apply the schema outside the app.
"""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from django.conf import settings

from clickhouse_driver import Client

from posthog.clickhouse.client import sync_execute
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DATA_BACKFILL_SQL, EXCHANGE_RATE_TABLE_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]

# Tables whose starting rows the app loads: (table name, function that builds the INSERT).
# Reference tables whose rows never change at runtime declare them in the schema instead.
SEED_DATA_TABLES = ((EXCHANGE_RATE_TABLE_NAME, EXCHANGE_RATE_DATA_BACKFILL_SQL),)


class ClickHouseDatabase:
    """The database named by `settings.CLICKHOUSE_DATABASE`."""

    # CREATE statements of every object, as ClickHouse reports them after `apply_schema`.
    _snapshot: ClassVar[dict[str, str]] = {}
    # Rows of every table that holds some after `apply_schema` and `seed`.
    _snapshot_rows: ClassVar[dict[str, list[tuple]]] = {}

    def __init__(self) -> None:
        self.name: str = settings.CLICKHOUSE_DATABASE

    def create(self) -> None:
        self._admin_execute(f"CREATE DATABASE IF NOT EXISTS `{self.name}`")

    def drop(self) -> None:
        # SYNC frees the replication paths, so that the schema can be applied again straight away.
        self._admin_execute(f"DROP DATABASE IF EXISTS `{self.name}` SYNC")

    def apply_schema(self, *, kafka: bool) -> None:
        """Creates every object the schema declares that the database does not have yet."""
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
        if settings.TEST:
            # The dev database on the same server uses the default replication paths.
            env["CLICKHOUSE_SCHEMA_ZK_PATH_SUFFIX"] = f"_{self.name}"
        result = subprocess.run(
            [str(REPO_ROOT / "bin" / "clickhouse-schema"), "apply", "-no-color"],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"bin/clickhouse-schema apply failed:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}")

    def snapshot(self) -> None:
        """Records the schema and the rows it declares, so that `restore` can rebuild both without running OpenTofu again."""
        rows = sync_execute(
            "SELECT name, create_table_query FROM system.tables WHERE database = %(database)s AND name NOT LIKE '.inner%%'",
            {"database": self.name},
        )
        # ClickHouse masks dictionary source passwords in the statements it reports.
        password = settings.CLICKHOUSE_PASSWORD.replace("\\", "\\\\").replace("'", "\\'")
        ClickHouseDatabase._snapshot = {
            name: query.replace("PASSWORD '[HIDDEN]'", f"PASSWORD '{password}'") for name, query in rows
        }
        tables_with_rows = sync_execute(
            "SELECT name FROM system.tables WHERE database = %(database)s AND engine LIKE '%%MergeTree' AND total_rows > 0",
            {"database": self.name},
        )
        ClickHouseDatabase._snapshot_rows = {
            name: sync_execute(f"SELECT * FROM `{name}`") for (name,) in tables_with_rows
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
        pending = list(self._snapshot.values())
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

    def _admin_execute(self, query: str) -> None:
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
            client.execute(query)
        finally:
            client.disconnect()
