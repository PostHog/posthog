from datetime import timedelta

# Full schedule ID is `SCHEDULE_ID_PREFIX-{team_id}`.
SCHEDULE_ID_PREFIX = "session-summarization-team"
WORKFLOW_NAME = "summarize-team-sessions"

# Value of the `PostHogScheduleType` search attribute set on every per-team schedule.
SCHEDULE_TYPE = "summarization-sweep"

SCHEDULE_INTERVAL = timedelta(minutes=5)

# Must be > SCHEDULE_INTERVAL so a session ending just before a tick is picked
# up on the next one.
SESSION_LOOKBACK_MINUTES = 30

MAX_SESSIONS_PER_TEAM = 10

CH_QUERY_MAX_EXECUTION_SECONDS = 180

# Must exceed FIND_ACTIVITY_TIMEOUT + child-start fan-out. Children are
# ABANDONED so their execution does not count against this budget.
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=5)

# Paired with maximum_attempts=1 — the next scheduled tick is the retry.
FIND_ACTIVITY_TIMEOUT = timedelta(seconds=200)

RECONCILER_SCHEDULE_ID = "session-summarization-sweep-reconciler-schedule"
RECONCILER_WORKFLOW_ID = "session-summarization-sweep-reconciler"
RECONCILER_WORKFLOW_NAME = "reconcile-summarization-schedules"

# Worst-case latency between enabling a source and its first per-team tick.
RECONCILER_INTERVAL = timedelta(minutes=1)

RECONCILER_EXECUTION_TIMEOUT = timedelta(minutes=5)

LIST_ENABLED_TEAMS_TIMEOUT = timedelta(seconds=60)
LIST_SCHEDULES_TIMEOUT = timedelta(seconds=120)
UPSERT_SCHEDULE_TIMEOUT = timedelta(seconds=60)
