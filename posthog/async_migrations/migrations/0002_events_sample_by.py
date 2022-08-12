from functools import cached_property
from typing import List

from django.conf import settings

from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
)
from posthog.async_migrations.disk_util import analyze_enough_disk_space_free_for_table
from posthog.async_migrations.utils import run_optimize_table
from posthog.client import sync_execute
from posthog.constants import AnalyticsDBMS
from posthog.models.instance_setting import set_instance_setting
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, CLICKHOUSE_REPLICATION
from posthog.version_requirement import ServiceVersionRequirement

TEMPORARY_TABLE_NAME = f"{CLICKHOUSE_DATABASE}.temp_events_0002_events_sample_by"
EVENTS_TABLE = "events"
EVENTS_TABLE_NAME = f"{CLICKHOUSE_DATABASE}.{EVENTS_TABLE}"
BACKUP_TABLE_NAME = f"{EVENTS_TABLE_NAME}_backup_0002_events_sample_by"
FAILED_EVENTS_TABLE_NAME = f"{EVENTS_TABLE_NAME}_failed"

"""
Migration Summary
- Context: https://github.com/PostHog/posthog/issues/5684
- Operations:
    0. Create a new table with the updated schema: `SAMPLE BY cityHash64(distinct_id)` + `ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`
    1. Start backfilling the new table (online) with data from partitions that are unlikely to be getting inserts (previous month and under)
    2. Detach the events_mv materialized view so we stop ingestion
    3. Insert the remaining events into the new table
    4. Rename the current table to `events_backup_0002_events_sample_by` and rename the new table to `events` (the table we use for querying)
    5. Attach the materialized view so we start ingestion again
    6. Optimize the table to remove duplicates
- Checks:
    0. is_required: only run this on instances with the old schema (new deploys get the new schema by default)
    1. precheck: make sure there's enough free disk space in CH to run the migration
    2. healthcheck: prevent CH from blowing up for lack of disk space
"""


def generate_insert_into_op(partition_gte: int, partition_lt=None) -> AsyncMigrationOperation:
    lt_expression = f"AND toYYYYMM(timestamp) < {partition_lt}" if partition_lt else ""
    op = AsyncMigrationOperationSQL(
        database=AnalyticsDBMS.CLICKHOUSE,
        sql=f"""
        INSERT INTO {TEMPORARY_TABLE_NAME}
        SELECT *
        FROM {EVENTS_TABLE}
        WHERE
            toYYYYMM(timestamp) >= {partition_gte} {lt_expression}
        """,
        rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}'",
        timeout_seconds=2 * 24 * 60 * 60,  # two days
    )
    return op


class Migration(AsyncMigrationDefinition):

    description = (
        "Schema change to the events table ensuring our SAMPLE BY clause is compatible with ClickHouse >=21.7.0."
    )

    depends_on = "0001_events_sample_by"

    posthog_min_version = "1.33.0"
    posthog_max_version = "1.33.9"

    service_version_requirements = [
        ServiceVersionRequirement(service="clickhouse", supported_version=">=21.6.0"),
    ]

    @cached_property
    def operations(self):
        if self._events_table_engine() == "Distributed":
            # Note: This _should_ be impossible but hard to ensure.
            raise RuntimeError("Cannot run the migration as `events` table is already Distributed engine.")

        create_table_op: List[AsyncMigrationOperation] = [
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                CREATE TABLE IF NOT EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}' AS {EVENTS_TABLE_NAME}
                ENGINE = ReplacingMergeTree(_timestamp)
                PARTITION BY toYYYYMM(timestamp)
                ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
                SAMPLE BY cityHash64(distinct_id)
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER '{CLICKHOUSE_CLUSTER}'",
            )
        ]

        old_partition_ops = []
        previous_partition = self._partitions[0] if len(self._partitions) > 0 else None
        for partition in self._partitions[1:]:
            old_partition_ops.append(generate_insert_into_op(previous_partition, partition))
            previous_partition = partition

        detach_mv_ops = [
            AsyncMigrationOperation(
                fn=lambda _: set_instance_setting("COMPUTE_MATERIALIZED_COLUMNS_ENABLED", False),
                rollback_fn=lambda _: set_instance_setting("COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True),
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"DETACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'",
                rollback=f"ATTACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'",
            ),
        ]

        last_partition_op = [generate_insert_into_op(self._partitions[-1] if len(self._partitions) > 0 else 0)]

        post_insert_ops = [
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                    RENAME TABLE
                        {EVENTS_TABLE_NAME} to {BACKUP_TABLE_NAME},
                        {TEMPORARY_TABLE_NAME} to {EVENTS_TABLE_NAME}
                    ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                """,
                rollback=f"""
                    RENAME TABLE
                        {EVENTS_TABLE_NAME} to {FAILED_EVENTS_TABLE_NAME},
                        {BACKUP_TABLE_NAME} to {EVENTS_TABLE_NAME}
                    ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                """,
            ),
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"ATTACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'",
                rollback=f"DETACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'",
            ),
            AsyncMigrationOperation(
                fn=lambda _: set_instance_setting("COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True),
                rollback_fn=lambda _: set_instance_setting("COMPUTE_MATERIALIZED_COLUMNS_ENABLED", False),
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0002_events_sample_by", query_id=query_id, table_name=EVENTS_TABLE_NAME, final=True
                )
            ),
        ]

        _operations = create_table_op + old_partition_ops + detach_mv_ops + last_partition_op + post_insert_ops
        return _operations

    def is_required(self):
        if settings.MULTI_TENANCY:
            return False

        table_engine = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": EVENTS_TABLE},
        )[0][0]

        if "Distributed" in table_engine:
            return False

        return (
            "ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))"
            not in table_engine
        )

    def precheck(self):
        events_failed_table_exists = sync_execute(f"EXISTS {FAILED_EVENTS_TABLE_NAME}")[0][0]
        if events_failed_table_exists:
            return (
                False,
                f"{FAILED_EVENTS_TABLE_NAME} already exists. We use this table as a backup if the migration fails. You can delete or rename it and restart the migration.",
            )

        events_table = "sharded_events" if CLICKHOUSE_REPLICATION else "events"
        return analyze_enough_disk_space_free_for_table(events_table, required_ratio=1.5)

    def healthcheck(self):
        result = sync_execute("SELECT free_space FROM system.disks")
        # 100mb or less left
        if int(result[0][0]) < 100000000:
            return (False, "ClickHouse available storage below 100MB")

        return (True, None)

    @cached_property
    def _partitions(self):
        return list(
            sorted(
                row[0]
                for row in sync_execute(
                    f"SELECT DISTINCT toUInt32(partition) FROM system.parts WHERE database = %(database)s AND table='{EVENTS_TABLE}'",
                    {"database": CLICKHOUSE_DATABASE},
                )
            )
        )

    def _events_table_engine(self) -> str:
        rows = sync_execute(
            "SELECT engine FROM system.tables WHERE database = %(database)s AND name = 'events'",
            {"database": CLICKHOUSE_DATABASE},
        )
        return rows[0][0]
