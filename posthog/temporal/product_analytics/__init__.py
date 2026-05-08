from posthog.temporal.backfill_materialized_property import (
    ACTIVITIES as BACKFILL_ACTIVITIES,
    BackfillMaterializedPropertiesBatchWorkflow,
    CompactMaterializedColumnsWorkflow,
)

from .upgrade_queries_activities import get_insights_to_migrate, migrate_insights_batch
from .upgrade_queries_workflow import UpgradeQueriesWorkflow

WORKFLOWS = [
    UpgradeQueriesWorkflow,
    BackfillMaterializedPropertiesBatchWorkflow,
    CompactMaterializedColumnsWorkflow,
]
ACTIVITIES = [
    get_insights_to_migrate,
    migrate_insights_batch,
    *BACKFILL_ACTIVITIES,
]
