from datetime import timedelta

SCHEDULE_ID = "session-summary-cleanup-sweep-schedule"
WORKFLOW_ID = "session-summary-cleanup-sweep"
WORKFLOW_NAME = "session-summary-cleanup-sweep"
SCHEDULE_TYPE = "session-summary-cleanup-sweep"

SCHEDULE_INTERVAL = timedelta(minutes=30)

# Must exceed worst-case `summarize-session` runtime (~45 min including retries).
AGE_THRESHOLD = timedelta(hours=4)

LIST_PAGE_SIZE = 100
DESCRIBE_CONCURRENCY = 20
DELETE_CONCURRENCY = 10
MAX_FILES_PER_SWEEP = 5000

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=20)
SWEEP_ACTIVITY_TIMEOUT = timedelta(minutes=15)
SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(minutes=2)

DISPLAY_NAME_WORKFLOW_PREFIX = "session-summary:single:"


def display_name_prefix_for(deployment: str) -> str:
    """Per-deployment prefix on Gemini ``display_name``. Keeps one deployment's sweeper from reaping another's files."""
    return f"{deployment}:{DISPLAY_NAME_WORKFLOW_PREFIX}"
