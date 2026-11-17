from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.run_mode import run_mode
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_DATA_TABLE,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)

# The ClickHouse team drops the column on the cloud clusters first, so IF EXISTS makes this a no-op there.
DROP_SURFACING_SCORE = "ALTER TABLE {table_name} DROP COLUMN IF EXISTS surfacing_score"

operations = [
    run_sql_with_exceptions(
        DROP_SURFACING_SCORE.format(table_name="session_replay_events"),
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DROP_SURFACING_SCORE.format(table_name=SESSION_REPLAY_EVENTS_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]

# Cloud ingestion never carried the column; only the local MSK Kafka table, its view and the writable table did.
if not run_mode().is_deployed_cloud:
    operations += [
        run_sql_with_exceptions(
            DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
        ),
        run_sql_with_exceptions(
            DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
        ),
        run_sql_with_exceptions(
            DROP_SURFACING_SCORE.format(table_name="writable_session_replay_events"),
            node_roles=[NodeRole.DATA, NodeRole.INGESTION_SMALL],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
        ),
        run_sql_with_exceptions(
            SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
        ),
    ]
