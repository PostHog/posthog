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

# Enumeration is a single Postgres read — fast even for hundreds of tables.
ENUMERATE_ACTIVITY_TIMEOUT = timedelta(seconds=60)
ENUMERATE_HEARTBEAT_TIMEOUT = timedelta(seconds=30)
ENUMERATE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=300)

# Upsert batches process up to BATCH_SIZE tables and all their columns in one
# transaction. With BATCH_SIZE=25 and typical column counts, each batch is a
# few hundred Postgres writes — generous timeouts cover slow disks during DEBUG.
UPSERT_ACTIVITY_TIMEOUT = timedelta(seconds=180)
UPSERT_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
UPSERT_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=600)

# Number of tables (with their columns) processed per upsert activity. Keeps
# activity inputs well under Temporal's 2MiB payload limit and bounds retry cost.
BATCH_SIZE = 25

# Relationship-proposal activities walk a few hundred FKs / joins / saved
# queries at most. Each iteration is a single facade write — generous timeouts
# accommodate slow Postgres during DEBUG.
PROPOSE_ACTIVITY_TIMEOUT = timedelta(seconds=120)
PROPOSE_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
PROPOSE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=300)
