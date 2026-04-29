from posthog.temporal.backfill_materialized_property import (
    ACTIVITIES as BACKFILL_ACTIVITIES,
    BackfillMaterializedPropertiesBatchWorkflow,
    BackfillMaterializedPropertyWorkflow,
    CompactMaterializedColumnsWorkflow,
)

from .upgrade_queries_activities import get_insights_to_migrate, migrate_insights_batch
from .upgrade_queries_workflow import UpgradeQueriesWorkflow

WORKFLOWS = [
    UpgradeQueriesWorkflow,
    BackfillMaterializedPropertyWorkflow,
    BackfillMaterializedPropertiesBatchWorkflow,
    CompactMaterializedColumnsWorkflow,
]
ACTIVITIES = [
    get_insights_to_migrate,
    migrate_insights_batch,
    *BACKFILL_ACTIVITIES,
]
