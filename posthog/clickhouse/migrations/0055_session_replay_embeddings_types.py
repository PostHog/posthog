from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_embeddings_migrations import (
    DISTRIBUTED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN,
    SHARDED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN,
    WRITEABLE_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN,
)

operations = [
    run_sql_with_exceptions(DISTRIBUTED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN()),
    run_sql_with_exceptions(WRITEABLE_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN()),
    run_sql_with_exceptions(SHARDED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN()),
]
