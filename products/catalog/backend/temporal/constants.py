"""Configuration constants for the catalog traversal workflow."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Identity
WORKFLOW_NAME = "catalog-traversal"
WORKFLOW_ID_PREFIX = "catalog-traversal"

# Workflow-level timeout — the whole pass should finish well under this even
# for large teams. Tightened as the agentic phase lands.
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)

# Lifecycle activities (create / complete / fail run) are single Postgres
# writes — keep them snappy with aggressive retries on transient errors.
RUN_LIFECYCLE_ACTIVITY_TIMEOUT = timedelta(seconds=30)
RUN_LIFECYCLE_HEARTBEAT_TIMEOUT = timedelta(seconds=15)
RUN_LIFECYCLE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=120)

DEFAULT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    # ValueError / TypeError indicate a programmer error — retrying won't help.
    non_retryable_error_types=["ValueError", "TypeError"],
)
