from .upgrade_queries_workflow import (
    UpgradeQueriesWorkflow,
    get_insights_to_migrate,
    migrate_insights_batch,
)

WORKFLOWS = [
    UpgradeQueriesWorkflow,
]
ACTIVITIES = [
    get_insights_to_migrate,
    migrate_insights_batch,
]
