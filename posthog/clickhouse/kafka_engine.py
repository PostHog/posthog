# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!
from typing import Literal

from django.conf import settings

# Consumer group names for Kafka tables.
# US deployment uses named groups after the cluster reshard, other deployments use legacy group names.
# Once we make all envs match, we can remove the _US check
_US = settings.CLOUD_DEPLOYMENT == "US"
CONSUMER_GROUP_EVENTS_JSON = "clickhouse_events_json" if _US else "group1"
CONSUMER_GROUP_APP_METRICS = "clickhouse_app_metrics" if _US else "group1"
CONSUMER_GROUP_APP_METRICS2 = "clickhouse_app_metrics2" if _US else "group1"
CONSUMER_GROUP_INGESTION_WARNINGS = "clickhouse_ingestion_warnings" if _US else "group1"
CONSUMER_GROUP_SESSION_REPLAY_EVENTS = "clickhouse_session_replay_events" if _US else "group1"
CONSUMER_GROUP_LOG_ENTRIES = "clickhouse_log_entries_v3" if _US else "clickhouse_log_entries"
CONSUMER_GROUP_DOCUMENT_EMBEDDINGS = "clickhouse_document_embeddings2" if _US else "clickhouse_document_embeddings"
CONSUMER_GROUP_HEATMAPS = "clickhouse_heatmaps" if _US else "group1"
CONSUMER_GROUP_PRECALCULATED_EVENTS = "clickhouse_precalculated_events2" if _US else "clickhouse_prefiltered_events"
CONSUMER_GROUP_PRECALCULATED_PERSON_PROPERTIES = (
    "clickhouse_precalculated_person_properties2" if _US else "clickhouse_precalculated_person_properties"
)
CONSUMER_GROUP_DISTINCT_ID_USAGE = "clickhouse_distinct_id_usage"
CONSUMER_GROUP_TOPHOG = "clickhouse_tophog"

STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

KAFKA_ENGINE = "Kafka('{kafka_host}', '{topic}', '{group}', '{serialization}')"
KAFKA_NAMED_COLLECTION_ENGINE = "Kafka({named_collection_name}, kafka_topic_list = '{topic}', kafka_group_name = '{group}', kafka_format = '{serialization}')"

KAFKA_PROTO_ENGINE = """
    Kafka () SETTINGS
    kafka_broker_list = '{kafka_host}',
    kafka_topic_list = '{topic}',
    kafka_group_name = '{group}',
    kafka_format = 'Protobuf',
    kafka_schema = '{proto_schema}',
    kafka_skip_broken_messages = {skip_broken_messages}
    """

GENERATE_UUID_SQL = """
SELECT generateUUIDv4()
"""

# The kafka_engine automatically adds these columns to the kafka tables. We use
# this string to add them to the other tables as well.
KAFKA_COLUMNS = """
, _timestamp DateTime
, _offset UInt64
"""

# Use this with new tables, old one didn't include partition
KAFKA_COLUMNS_WITH_PARTITION = """
, _timestamp DateTime
, _offset UInt64
, _partition UInt64
"""

KAFKA_TIMESTAMP_MS_COLUMN = "_timestamp_ms DateTime64"


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
        kafka_host = ",".join(settings.KAFKA_HOSTS_FOR_CLICKHOUSE)
    return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization=serialization)


def ttl_period(field: str = "created_at", amount: int = 3, unit: Literal["DAY", "WEEK"] = "WEEK") -> str:
    return "" if settings.TEST else f"TTL toDate({field}) + INTERVAL {amount} {unit}"


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"
