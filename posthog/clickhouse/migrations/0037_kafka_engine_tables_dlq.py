from infi.clickhouse_orm import migrations

from posthog.clickhouse.plugin_log_entries import (
    KAFKA_PLUGIN_LOG_ENTRIES_DLQ_MV_SQL,
    KAFKA_PLUGIN_LOG_ENTRIES_DLQ_SQL,
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
)
from posthog.models.app_metrics.sql import (
    APP_METRICS_MV_TABLE_SQL,
    KAFKA_APP_METRICS_DLQ_MV_SQL,
    KAFKA_APP_METRICS_DLQ_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
)
from posthog.models.event.sql import (
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_JSON_DLQ_MV_SQL,
    KAFKA_EVENTS_JSON_DLQ_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
)
from posthog.models.group.sql import (
    GROUPS_TABLE_MV_SQL,
    KAFKA_GROUPS_DLQ_MV_SQL,
    KAFKA_GROUPS_DLQ_SQL,
    KAFKA_GROUPS_TABLE_SQL,
)
from posthog.models.ingestion_warnings.sql import (
    INGESTION_WARNINGS_MV_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_DLQ_MV_SQL,
    KAFKA_INGESTION_WARNINGS_DLQ_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
)
from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID2_DLQ_MV_SQL,
    KAFKA_PERSON_DISTINCT_ID2_DLQ_SQL,
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    KAFKA_PERSON_DLQ_MV_SQL,
    KAFKA_PERSON_DLQ_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSON_DISTINCT_ID2_MV_SQL,
    PERSONS_TABLE_MV_SQL,
)
from posthog.models.session_recording_event.sql import (
    KAFKA_SESSION_RECORDING_EVENTS_DLQ_MV_SQL,
    KAFKA_SESSION_RECORDING_EVENTS_DLQ_SQL,
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

# Sets up a dead letter queue materialized view for each Kafka Engine table
# This view stores the raw messages and errors we encountered when trying to insert
# data into the main table via the Kafka Engine table + corresponding materialized view

operations = [
    # events_json
    migrations.RunSQL(f"DROP TABLE events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_EVENTS_TABLE_JSON_SQL()),
    migrations.RunSQL(KAFKA_EVENTS_JSON_DLQ_SQL()),
    migrations.RunSQL(KAFKA_EVENTS_JSON_DLQ_MV_SQL()),
    migrations.RunSQL(EVENTS_TABLE_JSON_MV_SQL()),
    # session_recording_events
    migrations.RunSQL(f"DROP TABLE session_recording_events_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_session_recording_events ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_DLQ_SQL()),
    migrations.RunSQL(KAFKA_SESSION_RECORDING_EVENTS_DLQ_MV_SQL()),
    migrations.RunSQL(SESSION_RECORDING_EVENTS_TABLE_MV_SQL()),
    # persons
    migrations.RunSQL(f"DROP TABLE person_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_person ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERSON_DLQ_SQL()),
    migrations.RunSQL(KAFKA_PERSON_DLQ_MV_SQL()),
    migrations.RunSQL(PERSONS_TABLE_MV_SQL),
    # person_distinct_id2
    migrations.RunSQL(f"DROP TABLE person_distinct_id2_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_person_distinct_id2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERSON_DISTINCT_ID2_DLQ_SQL()),
    migrations.RunSQL(KAFKA_PERSON_DISTINCT_ID2_DLQ_MV_SQL()),
    migrations.RunSQL(PERSON_DISTINCT_ID2_MV_SQL),
    # plugin_log_entries
    migrations.RunSQL(f"DROP TABLE plugin_log_entries_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_plugin_log_entries ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PLUGIN_LOG_ENTRIES_DLQ_SQL()),
    migrations.RunSQL(KAFKA_PLUGIN_LOG_ENTRIES_DLQ_MV_SQL()),
    migrations.RunSQL(PLUGIN_LOG_ENTRIES_TABLE_MV_SQL),
    # app_metrics
    migrations.RunSQL(f"DROP TABLE app_metrics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_APP_METRICS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_APP_METRICS_DLQ_SQL()),
    migrations.RunSQL(KAFKA_APP_METRICS_DLQ_MV_SQL()),
    migrations.RunSQL(APP_METRICS_MV_TABLE_SQL()),
    # ingestion_warnings
    migrations.RunSQL(f"DROP TABLE ingestion_warnings_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_ingestion_warnings ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_INGESTION_WARNINGS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_INGESTION_WARNINGS_DLQ_SQL()),
    migrations.RunSQL(KAFKA_INGESTION_WARNINGS_DLQ_MV_SQL()),
    migrations.RunSQL(INGESTION_WARNINGS_MV_TABLE_SQL()),
    # groups
    migrations.RunSQL(f"DROP TABLE groups_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE kafka_groups ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(KAFKA_GROUPS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_GROUPS_DLQ_SQL()),
    migrations.RunSQL(KAFKA_GROUPS_DLQ_MV_SQL()),
    migrations.RunSQL(GROUPS_TABLE_MV_SQL),
]
