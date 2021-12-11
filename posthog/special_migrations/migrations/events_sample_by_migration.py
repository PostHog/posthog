from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import EVENTS_TABLE, EVENTS_TABLE_SQL
from ee.clickhouse.sql.person import (
    PERSONS_DISTINCT_ID_TABLE,
)
from posthog.constants import AnalyticsDBMS
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE
from posthog.special_migrations.definition import SpecialMigrationDefinition, SpecialMigrationOperation
from posthog.version_requirement import ServiceVersionRequirement

ONE_DAY = 60 * 60 * 24

TEMPORARY_TABLE_NAME = "temp_events"


class Migration(SpecialMigrationDefinition):

    description = "Events table migration for compatible sample by column."

    posthog_min_version = "1.30.0"
    posthog_max_version = "1.31.0"

    service_version_requirements = [
        ServiceVersionRequirement(service="clickhouse", supported_version=">=21.6.0,<21.7.0"),
    ]

    operations = [
        SpecialMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=EVENTS_TABLE_SQL.replace(PERSONS_DISTINCT_ID_TABLE, TEMPORARY_TABLE_NAME, 1),
            rollback=f"DROP TABLE IF EXISTS {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
        ),
        SpecialMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
            INSERT INTO {TEMPORARY_TABLE_NAME}
            (uuid, event, properties, timestamp, team_id, distinct_id, elements_chain, created_at) 
            SELECT
            uuid,
            event,
            properties,
            timestamp,
            team_id,
            distinct_id,
            elements_chain,
            created_at 
            FROM {EVENTS_TABLE}""",
            rollback=f"TRUNCATE TABLE {TEMPORARY_TABLE_NAME} ON CLUSTER {CLICKHOUSE_CLUSTER}",
        ),
        # TODO: We need to reset the materialized columns after migration and before name swap
        SpecialMigrationOperation(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"""
                RENAME TABLE
                    {CLICKHOUSE_DATABASE}.{EVENTS_TABLE} to {CLICKHOUSE_DATABASE}.{EVENTS_TABLE}_old,
                    {CLICKHOUSE_DATABASE}.{TEMPORARY_TABLE_NAME} to {CLICKHOUSE_DATABASE}.{EVENTS_TABLE},
                ON CLUSTER {CLICKHOUSE_CLUSTER}
            """,
            rollback=f"""
                RENAME TABLE
                    {CLICKHOUSE_DATABASE}.{EVENTS_TABLE} to {CLICKHOUSE_DATABASE}.{EVENTS_TABLE}_failed,
                    {CLICKHOUSE_DATABASE}.{TEMPORARY_TABLE_NAME} to {CLICKHOUSE_DATABASE}.{EVENTS_TABLE},
                ON CLUSTER {CLICKHOUSE_CLUSTER}
            """,
        ),
    ]

    def healthcheck(self):
        result = sync_execute("""
        SELECT (free_space.size / event_table_size.size) FROM 
            (SELECT 1 as jc, 'event_table_size', sum(bytes) as size FROM system.parts WHERE table = 'sharded_events') event_table_size
        JOIN 
            (SELECT 1 as jc, 'free_disk_space', free_space as size FROM system.disks WHERE name = 'default') free_space
        ON event_table_size.jc=free_space.jc 
        """)
        event_size_to_free_space_ratio = result[0][0]
        # Require 1.5x the events table in free space to be available
        if event_size_to_free_space_ratio < 1.5:
            return (True, None)
        else:
            result = sync_execute("""
            SELECT formatReadableSize(free_space.size - (free_space.free_space - (1.5 * event_table_size.size ))) as required FROM 
                (SELECT 1 as jc, 'event_table_size', sum(bytes) as size FROM system.parts WHERE table = 'sharded_events') event_table_size
            JOIN 
                (SELECT 1 as jc, 'free_disk_space', free_space, total_space as size FROM system.disks WHERE name = 'default') free_space
            ON event_table_size.jc=free_space.jc
            """)
            required_space = result[0][0]
            return (False, f"Upgrade your ClickHouse storage to at least {required_space}.")

    def progress(self, _):
        result = sync_execute(f"SELECT COUNT(1) FROM {TEMPORARY_TABLE_NAME}")
        result2 = sync_execute(f"SELECT COUNT(1) FROM {EVENTS_TABLE}")
        total_events_to_move = result2[0][0]
        total_events_moved = result[0][0]

        progress = 100 * ( total_events_moved / total_events_to_move )
        return progress