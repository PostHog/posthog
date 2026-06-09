from datetime import timedelta

from temporalio.common import RetryPolicy

# Workflow + schedule identifiers.
COORDINATOR_WORKFLOW_NAME = "ai-observability-report-coordinator"
COORDINATOR_SCHEDULE_ID = "ai-observability-report-coordinator-schedule"
GENERATE_WORKFLOW_NAME = "generate-ai-observability-report"

# The coordinator just reads config rows and fans out — keep it short.
COORDINATOR_EXECUTION_TIMEOUT = timedelta(minutes=15)
FETCH_ACTIVITY_TIMEOUT = timedelta(seconds=60)
FETCH_RETRY_POLICY = RetryPolicy(maximum_attempts=3)

# The agent runs a full sandbox session (skill execution + MCP calls + Slack post), so the
# per-config workflow and its single activity get a generous budget — mirrors the signals
# custom-agent timeouts. maximum_attempts=1 so a missed heartbeat fails the run rather than
# spawning a duplicate sandbox session / double Slack post.
GENERATE_WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=90)
AGENT_ACTIVITY_TIMEOUT = timedelta(minutes=85)
AGENT_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
AGENT_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

# Bound how many configs one coordinator tick will dispatch concurrently.
DEFAULT_MAX_CONCURRENT_CONFIGS = 10
