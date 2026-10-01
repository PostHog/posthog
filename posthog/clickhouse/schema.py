from collections.abc import Callable

from posthog.clickhouse.dead_letter_queue import KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL
from posthog.clickhouse.log_entries import KAFKA_LOG_ENTRIES_AUX_TABLE_SQL, KAFKA_LOG_ENTRIES_TABLE_SQL
from posthog.clickhouse.metrics import KAFKA_METRICS_AVRO4_TABLE_SQL
from posthog.clickhouse.plugin_log_entries import KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL
from posthog.clickhouse.property_values import KAFKA_PROPERTY_VALUES_TABLE_SQL_FN
from posthog.heatmaps.sql import KAFKA_HEATMAPS_TABLE_SQL
from posthog.models.ai_events.sql import KAFKA_AI_EVENTS_TABLE_SQL
from posthog.models.app_metrics.sql import KAFKA_APP_METRICS_TABLE_SQL
from posthog.models.app_metrics2.sql import KAFKA_APP_METRICS2_TABLE_SQL
from posthog.models.cohortmembership.sql import KAFKA_COHORT_MEMBERSHIP_TABLE_SQL
from posthog.models.distinct_id_usage.sql import KAFKA_DISTINCT_ID_USAGE_TABLE_SQL
from posthog.models.event.sql import KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL, KAFKA_EVENTS_TABLE_JSON_SQL
from posthog.models.flag_evaluations.sql import KAFKA_FLAG_EVALUATIONS_TABLE_SQL
from posthog.models.group.sql import KAFKA_GROUPS_TABLE_SQL
from posthog.models.hog_invocation_results.sql import KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL
from posthog.models.ingestion_warnings.sql import KAFKA_INGESTION_WARNINGS_TABLE_SQL
from posthog.models.ingestion_warnings.sql_v2 import KAFKA_INGESTION_WARNINGS_V2_TABLE_SQL
from posthog.models.message_assets.sql import KAFKA_MESSAGE_ASSETS_TABLE_SQL
from posthog.models.performance.sql import KAFKA_PERFORMANCE_EVENTS_TABLE_SQL
from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
    KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
)
from posthog.models.person_overrides.sql import KAFKA_PERSON_OVERRIDES_TABLE_SQL
from posthog.models.precalculated_events.sql import KAFKA_PRECALCULATED_EVENTS_TABLE_SQL
from posthog.models.precalculated_person_properties.sql import KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL
from posthog.models.tophog.sql import KAFKA_TOPHOG_TABLE_SQL
from posthog.models.usage_ingestion.billing_usage_records import KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL
from posthog.session_recordings.sql.session_replay_event_sql import KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.session_recordings.sql.session_replay_feature_sql import KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL

from products.error_tracking.backend.embedding import KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL
from products.error_tracking.backend.sql import (
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL,
)

CREATE_KAFKA_TABLE_QUERIES = (
    KAFKA_LOG_ENTRIES_TABLE_SQL,
    KAFKA_LOG_ENTRIES_AUX_TABLE_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL,
    KAFKA_GROUPS_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    KAFKA_PERSON_OVERRIDES_TABLE_SQL,
    KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL,
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES_TABLE_SQL,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL,
    KAFKA_DOCUMENT_EMBEDDINGS_TABLE_SQL,
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_TABLE_SQL,
    KAFKA_INGESTION_WARNINGS_V2_TABLE_SQL,
    KAFKA_APP_METRICS_TABLE_SQL,
    KAFKA_APP_METRICS2_TABLE_SQL,
    KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
    KAFKA_MESSAGE_ASSETS_TABLE_SQL,
    KAFKA_PERFORMANCE_EVENTS_TABLE_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    KAFKA_SESSION_REPLAY_FEATURES_TABLE_SQL,
    KAFKA_HEATMAPS_TABLE_SQL,
    KAFKA_FLAG_EVALUATIONS_TABLE_SQL,
    KAFKA_PRECALCULATED_EVENTS_TABLE_SQL,
    KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL,
    KAFKA_COHORT_MEMBERSHIP_TABLE_SQL,
    KAFKA_DISTINCT_ID_USAGE_TABLE_SQL,
    KAFKA_TOPHOG_TABLE_SQL,
    KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL,
    KAFKA_AI_EVENTS_TABLE_SQL,
    KAFKA_PROPERTY_VALUES_TABLE_SQL_FN,
    KAFKA_METRICS_AVRO4_TABLE_SQL,
)


def build_query(query: str | Callable[[], str]) -> str:
    return query if isinstance(query, str) else query()
