from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_sql import (
    GROUPED_SESSION_REPLAY_EVENTS_VIEW_SQL,
)

operations = [
    run_sql_with_exceptions(GROUPED_SESSION_REPLAY_EVENTS_VIEW_SQL()),
]
