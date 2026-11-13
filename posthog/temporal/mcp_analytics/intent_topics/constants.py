"""Configuration for the MCP analytics intent topics pipeline (sync, assign, refit)."""

from datetime import timedelta

from temporalio.common import RetryPolicy

WORKFLOW_NAME = "mcpa-intent-topics"
COORDINATOR_WORKFLOW_NAME = "mcpa-intent-topics-coordinator"
CHILD_WORKFLOW_ID_PREFIX = "mcpa-intent-topics-team"

SYNC_SCHEDULE_ID = "mcpa-intent-topics-sync-schedule"
ASSIGN_SCHEDULE_ID = "mcpa-intent-topics-assign-schedule"
REFIT_SCHEDULE_ID = "mcpa-intent-topics-refit-schedule"

SYNC_INTERVAL = timedelta(hours=1)
ASSIGN_INTERVAL = timedelta(days=1)
REFIT_INTERVAL = timedelta(days=7)

# Each sync looks one hour back plus an overlap, so a late event is not missed between runs.
SYNC_WINDOW = timedelta(hours=1)
SYNC_OVERLAP = timedelta(minutes=15)
# The nightly assignment covers yesterday plus an overlap for vectors that landed after midnight.
ASSIGN_WINDOW = timedelta(days=1)
ASSIGN_OVERLAP = timedelta(hours=2)
# After a refit the whole fit window is re-assigned under the refreshed topics.
REFIT_REASSIGN_WINDOW = timedelta(days=7)

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=6)

SYNC_ACTIVITY_TIMEOUT = timedelta(minutes=10)
ASSIGN_ACTIVITY_TIMEOUT = timedelta(minutes=10)
REFIT_ACTIVITY_TIMEOUT = timedelta(minutes=15)
ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(seconds=60)

ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS = 4
