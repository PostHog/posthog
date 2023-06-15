from functools import cached_property

import structlog

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperationSQL
from posthog.constants import AnalyticsDBMS

logger = structlog.get_logger(__name__)


class Migration(AsyncMigrationDefinition):
    description = "Delete unused projection from sharded_events"

    depends_on = "0010_move_old_partitions"
    posthog_min_version = "1.43.0"
    posthog_max_version = "1.49.99"

    @cached_property
    def operations(self):
        operations = [
            AsyncMigrationOperationSQL(
                database=AnalyticsDBMS.CLICKHOUSE,
                sql=f"""
                ALTER TABLE sharded_events
                DROP PROJECTION IF EXISTS fast_max_kafka_timestamp_sharded_events
                SETTINGS mutations_sync = 2
                """,
                rollback=None,
                per_shard=True,
            ),
        ]

        return operations
