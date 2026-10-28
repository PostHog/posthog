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

# The nightly assignment covers yesterday plus an overlap for vectors that landed after midnight.
ASSIGN_WINDOW = timedelta(days=1)
ASSIGN_OVERLAP = timedelta(hours=2)
# After a refit every intent that still has a vector is re-assigned under the refreshed topics.
REFIT_REASSIGN_WINDOW = timedelta(days=30)

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
# Time in the task queue before each attempt starts.
WORKFLOW_QUEUE_MARGIN = timedelta(minutes=10)


def _all_attempts(activity_timeout: timedelta) -> timedelta:
    attempts = ACTIVITY_RETRY_POLICY.maximum_attempts or 1
    backoff = ACTIVITY_RETRY_POLICY.maximum_interval or timedelta(0)
    return activity_timeout * attempts + backoff * (attempts - 1)


# A child workflow must outlast every attempt of every activity it runs, or Temporal ends it while a
# retry could still succeed. The refit runs the refit and then the reassignment.
WORKFLOW_EXECUTION_TIMEOUTS: dict[str, timedelta] = {
    "sync": _all_attempts(SYNC_ACTIVITY_TIMEOUT) + WORKFLOW_QUEUE_MARGIN,
    "assign": _all_attempts(ASSIGN_ACTIVITY_TIMEOUT) + WORKFLOW_QUEUE_MARGIN,
    "refit": _all_attempts(REFIT_ACTIVITY_TIMEOUT) + _all_attempts(ASSIGN_ACTIVITY_TIMEOUT) + WORKFLOW_QUEUE_MARGIN,
}
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS = 4
