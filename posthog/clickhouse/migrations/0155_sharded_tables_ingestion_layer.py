from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import (
    DROP_KAFKA_LOG_ENTRIES_V3_TABLE_SQL,
    DROP_LOG_ENTRIES_TABLE_MV_SQL,
    KAFKA_LOG_ENTRIES_V3_TABLE_SQL,
    LOG_ENTRIES_V3_TABLE_MV_SQL,
    LOG_ENTRIES_WRITABLE_TABLE_SQL,
)
from posthog.heatmaps.sql import (
    DROP_HEATMAPS_TABLE_MV_SQL,
    DROP_KAFKA_HEATMAPS_TABLE_SQL,
    DROP_WRITABLE_HEATMAPS_TABLE_SQL,
    HEATMAPS_TABLE_MV_SQL,
    KAFKA_HEATMAPS_TABLE_SQL,
    WRITABLE_HEATMAPS_TABLE_SQL,
)
from posthog.models.app_metrics.sql import (
    APP_METRICS_MV_TABLE_SQL,
    DROP_APP_METRICS_MV_TABLE_SQL,
    DROP_KAFKA_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
    WRITABLE_APP_METRICS_TABLE_SQL,
)
from posthog.models.app_metrics2.sql import (
    APP_METRICS2_MV_TABLE_SQL,
    DROP_APP_METRICS2_MV_TABLE_SQL,
    DROP_KAFKA_APP_METRICS2_TABLE_SQL,
    KAFKA_APP_METRICS2_TABLE_SQL,
    WRITABLE_APP_METRICS2_TABLE_SQL,
)
from posthog.models.ingestion_warnings.sql import (
    DROP_INGESTION_WARNINGS_TABLE_MV_SQL,
    DROP_KAFKA_INGESTION_WARNINGS_TABLE_SQL,
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
    WRITABLE_INGESTION_WARNINGS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_HEATMAPS_TABLE_MV_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_WRITABLE_HEATMAPS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_HEATMAPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(WRITABLE_HEATMAPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(HEATMAPS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_APP_METRICS2_MV_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_APP_METRICS2_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_APP_METRICS2_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(WRITABLE_APP_METRICS2_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(APP_METRICS2_MV_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(DROP_APP_METRICS_MV_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_APP_METRICS_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(KAFKA_APP_METRICS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(WRITABLE_APP_METRICS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(APP_METRICS_MV_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(
        KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(DROP_LOG_ENTRIES_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_LOG_ENTRIES_V3_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(LOG_ENTRIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_LOG_ENTRIES_V3_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(LOG_ENTRIES_V3_TABLE_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_INGESTION_WARNINGS_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_INGESTION_WARNINGS_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(
        WRITABLE_INGESTION_WARNINGS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        KAFKA_INGESTION_WARNINGS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(INGESTION_WARNINGS_MV_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
