from typing import Literal

# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!
from django.conf import settings

from posthog.run_mode import run_mode

STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

KAFKA_ENGINE = "Kafka('{kafka_host}', '{topic}', '{group}', '{serialization}')"
KAFKA_NAMED_COLLECTION_ENGINE = "Kafka({named_collection_name}, kafka_topic_list = '{topic}', kafka_group_name = '{group}', kafka_format = '{serialization}')"


# The kafka_engine automatically adds these columns to the kafka tables. We use
# this string to add them to the other tables as well.
KAFKA_COLUMNS = """
, _timestamp DateTime
, _offset UInt64
"""


def kafka_engine(
    topic: str,
    kafka_host: str | None = None,
    group="group1",
    serialization="JSONEachRow",
    use_named_collection: bool = True,
    named_collection: str | None = None,
) -> str:
    if use_named_collection:
        assert kafka_host is None, "Can't set kafka_host when using named collection"
        # Use explicit named_collection if provided, otherwise default to MSK
        collection_name = named_collection or settings.CLICKHOUSE_KAFKA_NAMED_COLLECTION
        return KAFKA_NAMED_COLLECTION_ENGINE.format(
            named_collection_name=collection_name,
            topic=topic,
            group=group,
            serialization=serialization,
        )

    if kafka_host is None:
        raise ValueError("kafka_host is required when use_named_collection=False")
    return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization=serialization)


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"


def json_extract_trim_quotes(*args: str) -> str:
    """Build a ClickHouse SQL expression that extracts a JSON value as a trimmed string.

    Takes the same arguments as JSONExtractRaw (field, key1, key2, ...) and wraps the
    result to: strip surrounding quotes, convert empty string and literal 'null' to NULL.

    Three code paths must produce byte-identical output for the same input:
    - HogQL printer's JSON fallback (``_unsafe_json_extract_trim_quotes``)
    - SQL backfill mutation (``_generate_property_extraction_sql``)
    - Plugin-server live ingest (``jsonExtractRawAndTrimQuotes`` in create-event.ts)

    This function is the single source of truth for the SQL shape so the Python
    paths can't drift from each other. The TypeScript path is covered by the
    shared coercion fixture in ``coercion_fixtures.json``.
    """
    return f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw({', '.join(args)}), ''), 'null'), '^\"|\"$', '')"


# Consumer group names for Kafka tables.
# US deployment uses named groups after the cluster reshard, other deployments use legacy group names.
# Once we make all envs match, we can remove the _US check
_US = settings.CLOUD_DEPLOYMENT == "US"

CONSUMER_GROUP_EVENTS_JSON = "clickhouse_events_json" if _US else "group1"

CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON = "clickhouse_events_json_native_json"

# DEPRECATED: see posthog/models/app_metrics/sql.py for context. Kept only for the
# deprecated `kafka_app_metrics` table DDL.
CONSUMER_GROUP_APP_METRICS = "clickhouse_app_metrics" if _US else "group1"

CONSUMER_GROUP_APP_METRICS2 = "clickhouse_app_metrics2" if _US else "group1"

CONSUMER_GROUP_INGESTION_WARNINGS = "clickhouse_ingestion_warnings" if _US else "group1"

CONSUMER_GROUP_SESSION_REPLAY_EVENTS = "clickhouse_session_replay_events" if _US else "group1"

CONSUMER_GROUP_SESSION_REPLAY_FEATURES = "clickhouse_session_replay_features" if _US else "group1"

CONSUMER_GROUP_HOG_INVOCATION_RESULTS = "clickhouse_hog_invocation_results"

CONSUMER_GROUP_MESSAGE_ASSETS = "clickhouse_message_assets"

CONSUMER_GROUP_DOCUMENT_EMBEDDINGS = "clickhouse_document_embeddings2" if _US else "clickhouse_document_embeddings"

CONSUMER_GROUP_HEATMAPS = "clickhouse_heatmaps" if _US else "group1"

CONSUMER_GROUP_PRECALCULATED_EVENTS = "clickhouse_precalculated_events2" if _US else "clickhouse_prefiltered_events"

CONSUMER_GROUP_PRECALCULATED_PERSON_PROPERTIES = (
    "clickhouse_precalculated_person_properties2" if _US else "clickhouse_precalculated_person_properties"
)

CONSUMER_GROUP_DISTINCT_ID_USAGE = "clickhouse_distinct_id_usage"

CONSUMER_GROUP_TOPHOG = "clickhouse_tophog"

CONSUMER_GROUP_BILLING_USAGE_RECORDS = "clickhouse_billing_usage_records"

CONSUMER_GROUP_AI_EVENTS = "clickhouse_ai_events" if _US else "group1"

CONSUMER_GROUP_PROPERTY_VALUES = "clickhouse_property_values"

CONSUMER_GROUP_FLAG_EVALUATIONS = "clickhouse_flag_evaluations"

# v2 reads the same topic as v1 via its own consumer group, so it gets the full stream independently.
CONSUMER_GROUP_INGESTION_WARNINGS_V2 = "clickhouse_ingestion_warnings_v2"

# Use this with new tables, old one didn't include partition
KAFKA_COLUMNS_WITH_PARTITION = """
, _timestamp DateTime
, _offset UInt64
, _partition UInt64
"""


# Every stack outside deployed cloud runs a single-node Kafka whose topics have one partition,
# so a consumer group can place only one consumer. The other consumers never receive an
# assignment, and each one holds a thread and repeats the request, which writes a
# "Can't get assignment" warning every time. Cloud topics have many partitions, so they keep the
# tuned count. Resolve the mode per call, because a module-level constant would freeze the value
# at import and defeat a test that patches the mode.
def kafka_num_consumers(cloud_count: int) -> int:
    return cloud_count if run_mode().is_deployed_cloud else 1


def ttl_period(field: str = "created_at", amount: int = 3, unit: Literal["DAY", "WEEK"] = "WEEK") -> str:
    return "" if settings.TEST else f"TTL toDate({field}) + INTERVAL {amount} {unit}"
