"""Configuration constants for evaluation reports workflow."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Agent configuration
EVAL_REPORT_AGENT_MODEL = "gpt-5.2"
EVAL_REPORT_AGENT_RECURSION_LIMIT = 100
EVAL_REPORT_AGENT_TIMEOUT = 600.0  # 10 minutes

# Workflow names — all eval-reports Temporal surface is prefixed `llma-eval-reports-`
# to match the convention used by other LLMA products (clustering, summarization, sentiment).
SCHEDULE_ALL_EVAL_REPORTS_WORKFLOW_NAME = "llma-eval-reports-scheduled-coordinator"
CHECK_COUNT_TRIGGERED_REPORTS_WORKFLOW_NAME = "llma-eval-reports-count-triggered-coordinator"
GENERATE_EVAL_REPORT_WORKFLOW_NAME = "llma-eval-reports-generate-and-deliver"
SCHEDULE_ID = "llma-eval-reports-scheduled-coordinator-schedule"
COUNT_TRIGGER_SCHEDULE_ID = "llma-eval-reports-count-triggered-coordinator-schedule"

# Workflow timeouts
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=2)

# Activity timeouts
FETCH_ACTIVITY_TIMEOUT = timedelta(seconds=60)
PREPARE_ACTIVITY_TIMEOUT = timedelta(seconds=60)
AGENT_ACTIVITY_TIMEOUT = timedelta(seconds=660)  # 11 minutes (agent timeout + buffer)
STORE_ACTIVITY_TIMEOUT = timedelta(seconds=60)
DELIVER_ACTIVITY_TIMEOUT = timedelta(seconds=120)
UPDATE_SCHEDULE_ACTIVITY_TIMEOUT = timedelta(seconds=30)

# Heartbeat timeouts
AGENT_HEARTBEAT_TIMEOUT = timedelta(seconds=120)
DELIVER_HEARTBEAT_TIMEOUT = timedelta(seconds=60)

# Retry policies
FETCH_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

AGENT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

STORE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

DELIVER_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
)

UPDATE_SCHEDULE_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)
