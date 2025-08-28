from posthog.session_recordings.sql.session_replay_event_v2_test_sql import (
    DROP_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL,
    SESSION_REPLAY_EVENTS_V2_TEST_TABLES,
)

# NB the kafka and mv tables are first in this list
operations = [DROP_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(t) for t in SESSION_REPLAY_EVENTS_V2_TEST_TABLES]
