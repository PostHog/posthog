from django.conf import settings

ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS source_type LowCardinality(String)
"""

DISTRIBUTED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN = (
    lambda: ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN.format(
        table_name="session_replay_embeddings",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

WRITEABLE_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN = (
    lambda: ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN.format(
        table_name="writable_session_replay_embeddings",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

SHARDED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN = (
    lambda: ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_TYPE_COLUMN.format(
        table_name="sharded_session_replay_embeddings",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN = """
    ALTER TABLE {table_name} on CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS input String
"""

DISTRIBUTED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN = (
    lambda: ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN.format(
        table_name="session_replay_embeddings",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

WRITEABLE_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN = (
    lambda: ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN.format(
        table_name="writable_session_replay_embeddings",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

SHARDED_TABLE_ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN = (
    lambda: ALTER_SESSION_REPLAY_EMBEDDINGS_ADD_INPUT_COLUMN.format(
        table_name="sharded_session_replay_embeddings",
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)
