"""Per-team session summarization schedules.

Each team with `SignalSourceConfig(SESSION_ANALYSIS_CLUSTER, enabled=True)` has
a Temporal schedule firing every few minutes. A global reconciler workflow
keeps the set of schedules in sync with Postgres.
"""

from posthog.temporal.session_replay.summarization_sweep.activities import (
    delete_team_schedule_activity,
    find_sessions_for_team_activity,
    list_enabled_teams_activity,
    list_summarization_schedule_team_ids_activity,
    upsert_team_schedule_activity,
)
from posthog.temporal.session_replay.summarization_sweep.reconciler import ReconcileSummarizationSchedulesWorkflow
from posthog.temporal.session_replay.summarization_sweep.workflow import SummarizeTeamSessionsWorkflow

SUMMARIZATION_SWEEP_WORKFLOWS = [
    SummarizeTeamSessionsWorkflow,
    ReconcileSummarizationSchedulesWorkflow,
]
SUMMARIZATION_SWEEP_ACTIVITIES = [
    find_sessions_for_team_activity,
    delete_team_schedule_activity,
    list_enabled_teams_activity,
    list_summarization_schedule_team_ids_activity,
    upsert_team_schedule_activity,
]
