from constance import config
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import EVENTS_TABLE
from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.constants import AnalyticsDBMS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.version_requirement import ServiceVersionRequirement

MIGRATION_NAME = "sort_key_include_event"
TEMPORARY_TABLE_NAME = f"{CLICKHOUSE_DATABASE}.temp_{MIGRATION_NAME}"
EVENTS_TABLE_NAME = f"{CLICKHOUSE_DATABASE}.sharded_events"
BACKUP_TABLE_NAME = f"backup_{MIGRATION_NAME}"

# Karl: Probably need to add a new description


class Migration(AsyncMigrationDefinition):

    description = """
        Schema change to the events table ensuring we include `event` in the sort key replicated instances.

        Also encompasses SAMPLE BY changes from migration 0001.
    """

    posthog_min_version = "1.31.0"
    posthog_max_version = "1.32.0"
    # Karl: Not sure if needed

    service_version_requirements = [
        ServiceVersionRequirement(service="clickhouse", supported_version=">=21.6.0"),
    ]

    operations = [
        # Karl: zk path is chosen to be well recognizable but might need tweaking
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            CREATE TABLE IF NOT EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER} AS {EVENTS_TABLE_NAME}
            ENGINE = ReplicatedReplacingMergeTree('/clickhouse/prod/tables/{{shard}}/posthog.{MIGRATION_NAME}', '{{replica}}', _timestamp)
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
            SAMPLE BY cityHash64(distinct_id)
            SETTINGS storage_policy = 'hot_to_cold', index_granularity = 8192
            """,
            rollback=f"DROP TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
            resumable=True,
        ),
        # Karl: https://clickhouse.com/docs/en/sql-reference/statements/insert-into/#performance-considerations
        #   mentions to group data by a partition key before uploading it to ClickHouse. Not sure if we should add a sort key here
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            INSERT INTO {TEMPORARY_TABLE_NAME}
            SELECT *
            FROM {EVENTS_TABLE}
            WHERE timestamp < toDateTime64(toYYYYMM(now()) - 1, 6)
            AND timestamp >= (SELECT max(timestamp) FROM {TEMPORARY_TABLE_NAME})""",
            rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
            resumable=True,
            # Karl: Needs to run on all our ch nodes
            run_on_all_nodes=True,
        ),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"DETACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
            rollback=f"ATTACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
            side_effect=lambda: setattr(config, "MATERIALIZED_COLUMNS_ENABLED", False),
            side_effect_rollback=lambda: setattr(config, "MATERIALIZED_COLUMNS_ENABLED", True),
        ),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            INSERT INTO {TEMPORARY_TABLE_NAME}
            SELECT *
            FROM {EVENTS_TABLE}
            WHERE timestamp >= (SELECT max(timestamp) FROM {TEMPORARY_TABLE_NAME})""",
            rollback=f"TRUNCATE TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
            resumable=True,
            run_on_all_nodes=True,
        ),
        AsyncMigrationOperation(
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
        # Karl: Copied from previous migration. I don't think we should do this in cloud - super expensive
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"OPTIMIZE TABLE {EVENTS_TABLE_NAME} FINAL",
            rollback="",
            resumable=True,
            run_on_all_nodes=True,
        ),
        AsyncMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"ATTACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
            rollback=f"DETACH TABLE {EVENTS_TABLE_NAME}_mv ON CLUSTER {CLICKHOUSE_CLUSTER}",
            side_effect=lambda: setattr(config, "MATERIALIZED_COLUMNS_ENABLED", True),
            side_effect_rollback=lambda: setattr(config, "MATERIALIZED_COLUMNS_ENABLED", False),
        ),
    ]
    # Karl: Might need to update this + the other migration conditions?

    def is_required(self):
        return settings.CLICKHOUSE_REPLICATION

    # Karl: Should run on all nodes?
    def precheck(self):
        result = sync_execute(
            f"""
        SELECT (free_space.size / greatest(event_table_size.size, 1)) FROM
            (SELECT 1 as jc, 'event_table_size', sum(bytes) as size FROM system.parts WHERE table = 'sharded_events' AND database='{CLICKHOUSE_DATABASE}') event_table_size
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
                (SELECT 1 as jc, 'event_table_size', sum(bytes) as size FROM system.parts WHERE table = 'sharded_events' AND database='{CLICKHOUSE_DATABASE}') event_table_size
            JOIN
                (SELECT 1 as jc, 'free_disk_space', free_space, total_space as size FROM system.disks WHERE name = 'default') free_space
            ON event_table_size.jc=free_space.jc
            """
            )
            required_space = result[0][0]
            return (False, f"Upgrade your ClickHouse storage to at least {required_space}.")

    # Karl: Should run on all nodes?
    def healthcheck(self):
        result = sync_execute("SELECT free_space FROM system.disks")
        # 100mb or less left
        if int(result[0][0]) < 100000000:
            return (False, "ClickHouse available storage below 100MB")

        return (True, None)

    # Karl: Should run on all nodes?
    def progress(self, _):
        result = sync_execute(f"SELECT COUNT(1) FROM {TEMPORARY_TABLE_NAME}")
        result2 = sync_execute(f"SELECT COUNT(1) FROM {EVENTS_TABLE_NAME}")
        total_events_to_move = result2[0][0]
        total_events_moved = result[0][0]

        progress = 100 * (total_events_moved / total_events_to_move)
        return progress
