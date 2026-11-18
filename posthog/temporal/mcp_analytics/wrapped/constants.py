from datetime import timedelta

from temporalio.common import RetryPolicy

COORDINATOR_WORKFLOW_NAME = "mcpa-wrapped-coordinator"
COORDINATOR_SCHEDULE_ID = "mcpa-wrapped-coordinator-schedule"

# Per-project kill switch and rollout control. A project is computed only when this flag is on for it,
# so the yearly schedule does nothing until the flag targets someone.
COMPUTE_FEATURE_FLAG = "mcp-analytics-wrapped-compute"

MAX_CONCURRENT_TEAMS = 4

COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=24)

DISCOVERY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISCOVERY_RETRY_POLICY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))

# The aggregate query caps itself at 10 minutes, so one attempt fits inside this with room for the Postgres write.
GENERATE_ACTIVITY_TIMEOUT = timedelta(minutes=15)
GENERATE_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
# Offline replicas are busier and fail more often, so a project gets a few spaced retries before it counts as failed.
GENERATE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    maximum_interval=timedelta(minutes=5),
    backoff_coefficient=3.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)
