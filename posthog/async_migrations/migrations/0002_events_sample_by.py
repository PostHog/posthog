from constance import config
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import EVENTS_TABLE
from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.constants import AnalyticsDBMS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, CLICKHOUSE_REPLICATION
from posthog.version_requirement import ServiceVersionRequirement

TEMPORARY_TABLE_NAME = f"{CLICKHOUSE_DATABASE}.temp_events_0002_events_sample_by"
EVENTS_TABLE_NAME = f"{CLICKHOUSE_DATABASE}.{EVENTS_TABLE}"
BACKUP_TABLE_NAME = f"{EVENTS_TABLE_NAME}_backup_0002_events_sample_by"

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


class Migration(AsyncMigrationDefinition):

    description = (
        "Schema change to the events table ensuring our SAMPLE BY clause is compatible with ClickHouse >=21.7.0."
    )

    depends_on = "0001_events_sample_by"

    posthog_min_version = "1.30.0"
    posthog_max_version = "1.31.1"

    service_version_requirements = [
        ServiceVersionRequirement(service="clickhouse", supported_version=">=21.6.0,<21.7.0"),
    ]

    operations = [
        AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            CREATE TABLE IF NOT EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER} AS {EVENTS_TABLE_NAME}
            ENGINE = ReplacingMergeTree(_timestamp)
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
            SAMPLE BY cityHash64(distinct_id) 
            """,
            rollback=f"DROP TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
            resumable=True,
        ),
        AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            INSERT INTO {TEMPORARY_TABLE_NAME}
            SELECT * 
            FROM {EVENTS_TABLE}
            WHERE timestamp < toDateTime64(toYYYYMM(now()) - 1, 6)
            AND timestamp >= (SELECT max(timestamp) FROM {TEMPORARY_TABLE_NAME})""",
            rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
            resumable=True,
            timeout_seconds=7 * 24 * 60 * 60,  # one week
        ),
        AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"DETACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
            rollback=f"ATTACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
        ),
        AsyncMigrationOperation(
            fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", False),
            rollback_fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True),
        ),
        AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            INSERT INTO {TEMPORARY_TABLE_NAME}
            SELECT * 
            FROM {EVENTS_TABLE}
            WHERE timestamp >= (SELECT max(timestamp) FROM {TEMPORARY_TABLE_NAME})""",
            rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
            resumable=True,
            timeout_seconds=3 * 24 * 60 * 60,  # three days
        ),
        AsyncMigrationOperation.simple_op(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                RENAME TABLE
                    {EVENTS_TABLE_NAME} to {BACKUP_TABLE_NAME},
                    {TEMPORARY_TABLE_NAME} to {EVENTS_TABLE_NAME}
                ON CLUSTER {CLICKHOUSE_CLUSTER}
            """,
            rollback=f"""
                RENAME TABLE
                    {EVENTS_TABLE_NAME} to {EVENTS_TABLE_NAME}_failed,
                    {BACKUP_TABLE_NAME} to {EVENTS_TABLE_NAME}
                ON CLUSTER {CLICKHOUSE_CLUSTER}
            """,
        ),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"OPTIMIZE TABLE {EVENTS_TABLE_NAME} FINAL",
            rollback="",
            resumable=True,
        ),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"ATTACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
            rollback=f"DETACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
        ),
        AsyncMigrationOperation(
            fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True),
            rollback_fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", False),
        ),
    ]

    def is_required(self):
        if settings.MULTI_TENANCY:
            return False

        res = sync_execute(f"SHOW CREATE TABLE {EVENTS_TABLE_NAME}")
        return (
            "ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))" not in res[0][0]
        )

    def precheck(self):
        events_table = "sharded_events" if CLICKHOUSE_REPLICATION else "events"
        result = sync_execute(
            f"""
        SELECT (free_space.size / greatest(event_table_size.size, 1)) FROM 
            (SELECT 1 as jc, 'event_table_size', sum(bytes) as size FROM system.parts WHERE table = '{events_table}' AND database='{CLICKHOUSE_DATABASE}') event_table_size
        JOIN 
            (SELECT 1 as jc, 'free_disk_space', free_space as size FROM system.disks WHERE name = 'default') free_space
        ON event_table_size.jc=free_space.jc 
        """
        )
        event_size_to_free_space_ratio = result[0][0]

        # Require 1.5x the events table in free space to be available
        if event_size_to_free_space_ratio > 1.5:
            return (True, None)
        else:
            result = sync_execute(
                f"""
            SELECT formatReadableSize(free_space.size - (free_space.free_space - (1.5 * event_table_size.size ))) as required FROM 
                (SELECT 1 as jc, 'event_table_size', sum(bytes) as size FROM system.parts WHERE table = '{events_table}' AND database='{CLICKHOUSE_DATABASE}') event_table_size
            JOIN 
                (SELECT 1 as jc, 'free_disk_space', free_space, total_space as size FROM system.disks WHERE name = 'default') free_space
            ON event_table_size.jc=free_space.jc
            """
            )
            required_space = result[0][0]
            return (False, f"Upgrade your ClickHouse storage to at least {required_space}.")

    def healthcheck(self):
        result = sync_execute("SELECT free_space FROM system.disks")
        # 100mb or less left
        if int(result[0][0]) < 100000000:
            return (False, "ClickHouse available storage below 100MB")

        return (True, None)

    def progress(self, _):
        result = sync_execute(f"SELECT COUNT(1) FROM {TEMPORARY_TABLE_NAME}")
        result2 = sync_execute(f"SELECT COUNT(1) FROM {EVENTS_TABLE_NAME}")
        total_events_to_move = result2[0][0]
        total_events_moved = result[0][0]

        progress = 100 * (total_events_moved / total_events_to_move)
        return progress
