from posthog.temporal.enforce_max_replay_retention.activities import enforce_max_replay_retention
from posthog.temporal.enforce_max_replay_retention.workflows import EnforceMaxReplayRetentionWorkflow

WORKFLOWS = [
    EnforceMaxReplayRetentionWorkflow,
]

ACTIVITIES = [enforce_max_replay_retention]
