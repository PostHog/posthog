import structlog
from django.conf import settings

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperationSQL
from posthog.client import sync_execute
from posthog.constants import AnalyticsDBMS
from posthog.version_requirement import ServiceVersionRequirement

logger = structlog.get_logger(__name__)


class Migration(AsyncMigrationDefinition):
    description = "Create a projection on max(_timestamp) to speed up `clickhouse_lag` celery task. Requires ClickHouse 22.3 or above"

    depends_on = "0007_persons_and_groups_on_events_backfill"

    posthog_min_version = "1.41.0"
    posthog_max_version = "1.45.99"

    service_version_requirements = [ServiceVersionRequirement(service="clickhouse", supported_version=">=22.3.0")]

    def is_required(self):
        __import__("IPython").embed()  # FIXME
        return "fast_max_kafka_timestamp" not in self.get_table_definition()

    def get_table_definition(self) -> str:
        result = sync_execute(
            "SELECT create_table_query FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": "sharded_events"},
        )
        return result[0][0] if len(result) > 0 else ""

    operations = [
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' ADD PROJECTION fast_max_kafka_timestamp (SELECT max(_timestamp))",
            rollback=f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' DROP PROJECTION fast_max_kafka_timestamp",
        ),
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MATERIALIZE PROJECTION fast_max_kafka_timestamp",
            rollback=None,
        ),
    ]
