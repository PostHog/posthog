from typing import Optional, cast

from django.conf import settings

import structlog

from posthog.async_migrations.definition import AsyncMigrationDefinition
from posthog.clickhouse.client import sync_execute

logger = structlog.get_logger(__name__)

"""
Migration summary:

Schema change to migrate tables to support replication and more than one shard.

This allows for higher scalability as more hosts can be added under ClickHouse.

The migration strategy:

    1. We have a list of tables that might need replacing below.
    2. For each one, we replace the current engine with the appropriate Replicated by:
        a. creating a new table with the right engine and identical schema
        b. temporarily stopping ingestion to the table by dropping the kafka table
        c. using `ALTER TABLE ATTACH/DROP PARTITIONS` to move data to the new table.
        d. rename tables
    3. Once all tables are updated, we create the required distributed tables and re-enable ingestion

We use ATTACH/DROP tables to do the table migration instead of a normal INSERT. This method allows
moving data without increasing disk usage between identical schemas.

`events` and `session_recording_events` require extra steps as they're also sharded:

    1. The new table should be named `sharded_TABLENAME`
    2. When re-enabling ingestion, we create `TABLENAME` and `writable_TABLENAME` tables
       which are responsible for distributed reads and writes
    3. We re-create materialized views to write to `writable_TABLENAME`

Constraints:

    1. This migration relies on there being exactly one ClickHouse node when it's run.
    2. For person and events tables, the schema tries to preserve any materialized columns.
    3. This migration requires there to be no ongoing part merges while it's executing.
    4. This migration depends on 0002_events_sample_by. If it didn't, this could be a normal migration.
    5. This migration depends on the person_distinct_id2 async migration to have completed.
    6. We can't stop ingestion by dropping/detaching materialized view as we can't restore to the right (non-replicated) schema afterwards.
    7. Async migrations might fail _before_ a step executes and rollbacks need to account for that, which complicates renaming logic.
    8. For person_distinct_id2 table moving parts might fail due to upstream issues with zookeeper parts being created automatically. We retry up to 3 times.
"""


class Migration(AsyncMigrationDefinition):
    description = "Replace tables with replicated counterparts"

    depends_on = "0003_fill_person_distinct_id2"

    posthog_min_version = "1.36.1"
    posthog_max_version = "1.36.99"

    def is_required(self):
        return "Distributed" not in cast(str, self.get_current_engine("events"))

    def get_current_engine(self, table_name: str) -> Optional[str]:
        result = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": table_name},
        )

        return result[0][0] if len(result) > 0 else None

    # Check older versions of the file for the migration code
