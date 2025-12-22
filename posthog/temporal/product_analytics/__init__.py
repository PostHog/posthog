from posthog.temporal.backfill_materialized_property import (
    ACTIVITIES as BACKFILL_ACTIVITIES,
    BackfillMaterializedPropertyWorkflow,
)
from posthog.temporal.eav_backfill import (
    ACTIVITIES as EAV_BACKFILL_ACTIVITIES,
    BackfillEAVPropertyWorkflow,
)

from .upgrade_queries_activities import get_insights_to_migrate, migrate_insights_batch
from .upgrade_queries_workflow import UpgradeQueriesWorkflow

WORKFLOWS = [
    UpgradeQueriesWorkflow,
    BackfillMaterializedPropertyWorkflow,
    BackfillEAVPropertyWorkflow,
]
ACTIVITIES = [
    get_insights_to_migrate,
    migrate_insights_batch,
    *BACKFILL_ACTIVITIES,
    *EAV_BACKFILL_ACTIVITIES,
]
