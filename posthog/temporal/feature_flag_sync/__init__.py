from posthog.temporal.feature_flag_sync.workflow import (
    SyncFeatureFlagLastCalledWorkflow,
    sync_feature_flag_last_called_activity,
)

WORKFLOWS = [
    SyncFeatureFlagLastCalledWorkflow,
]

ACTIVITIES = [
    sync_feature_flag_last_called_activity,
]
