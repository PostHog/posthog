import structlog
from django.conf import settings

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperationSQL
from posthog.constants import AnalyticsDBMS
from posthog.version_requirement import ServiceVersionRequirement

logger = structlog.get_logger(__name__)


class Migration(AsyncMigrationDefinition):
    description = "Create a projection on max(_timestamp) to speed up `clickhouse_lag` celery task. Requires ClickHouse 22.3 or above"

    depends_on = "0007_persons_and_groups_on_events_backfill"

    posthog_min_version = "1.41.0"
    posthog_max_version = "1.45.99"

    service_version_requirements = [ServiceVersionRequirement(service="clickhouse", supported_version=">=22.3.0")]

    operations = [
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' ADD PROJECTION fast_max_kafka_timestamp (SELECT max(_timestamp))",
            rollback=f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' ADD PROJECTION fast_max_kafka_timestamp (SELECT max(_timestamp))",
        ),
        AsyncMigrationOperationSQL(
            database=AnalyticsDBMS.CLICKHOUSE,
            sql=f"ALTER TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MATERIALIZE PROJECTION fast_max_kafka_timestamp",
            rollback=None,
        ),
    ]
