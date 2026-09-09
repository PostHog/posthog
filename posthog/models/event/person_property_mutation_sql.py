from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON

PERSON_PROPERTY_MUTATION_COLUMNS = """
    team_id Int64,
    event_uuid UUID,
    properties String,
    ingested_at DateTime('UTC')
"""


def PERSON_PROPERTY_MUTATION_LOG_DATA_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS person_property_mutation_log_data
({PERSON_PROPERTY_MUTATION_COLUMNS})
ENGINE = {ReplacingMergeTree("person_property_mutation_log_data", ver="ingested_at")}
PARTITION BY toDate(ingested_at)
ORDER BY (team_id, event_uuid)
TTL ingested_at + INTERVAL 30 DAY
SETTINGS index_granularity = 1024, ttl_only_drop_parts = 1
"""


def PERSON_PROPERTY_MUTATION_LOG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS person_property_mutation_log
({PERSON_PROPERTY_MUTATION_COLUMNS})
ENGINE = {Distributed(data_table="person_property_mutation_log_data", cluster=settings.CLICKHOUSE_AUX_CLUSTER)}
"""


def PERSON_PROPERTY_MUTATION_LOG_KAFKA_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS kafka_person_property_mutation_log
(
    team_id Int64,
    uuid UUID,
    properties String
)
ENGINE = {kafka_engine(topic=KAFKA_EVENTS_JSON, group="clickhouse_person_property_mutation_log", named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION)}
"""


def PERSON_PROPERTY_MUTATION_LOG_MV_SQL() -> str:
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS person_property_mutation_log_mv
TO person_property_mutation_log
AS SELECT
    team_id,
    uuid AS event_uuid,
    concat('{', arrayStringConcat(arrayMap(
        property -> concat(toJSONString(property.1), ':', property.2),
        arrayFilter(property -> property.1 IN ('$set', '$set_once', '$unset'),
            JSONExtractKeysAndValuesRaw(source.properties))
    ), ','), '}') AS properties,
    toDateTime(_timestamp, 'UTC') AS ingested_at
FROM kafka_person_property_mutation_log AS source
WHERE JSONHas(source.properties, '$set') OR JSONHas(source.properties, '$set_once') OR JSONHas(source.properties, '$unset')
"""
