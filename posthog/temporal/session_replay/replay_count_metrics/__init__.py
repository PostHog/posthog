from posthog.temporal.session_replay.replay_count_metrics.activities import collect_replay_count_metrics
from posthog.temporal.session_replay.replay_count_metrics.workflow import ReplayCountMetricsWorkflow

REPLAY_COUNT_METRICS_WORKFLOWS = [
    ReplayCountMetricsWorkflow,
]

REPLAY_COUNT_METRICS_ACTIVITIES = [collect_replay_count_metrics]
