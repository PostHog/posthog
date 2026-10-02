from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_BILLING_USAGE_RECORDS, kafka_engine
from posthog.kafka_client.topics import KAFKA_BILLING_USAGE_RECORDS

BILLING_USAGE_RECORDS_TABLE = "billing_usage_records"

KAFKA_BILLING_USAGE_RECORDS_TABLE = f"kafka_{BILLING_USAGE_RECORDS_TABLE}"

# Event-derived producers use trusted server capture time when available; aggregate producers use
# their emission clock. Never use customer-supplied timestamps, which would let a customer control
# whether their records deduplicate.
BASE_BILLING_USAGE_RECORDS_COLUMNS = """
    schema_version UInt8,
    record_id String,
    producer_id LowCardinality(String),
    team_id Int64,
    organization_id UUID,
    usage_key LowCardinality(String),
    unit LowCardinality(String),
    quantity Int64,
    timestamp DateTime64(6, 'UTC'),
    inserted_at DateTime64(6, 'UTC')
""".strip()


def KAFKA_BILLING_USAGE_RECORDS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_BILLING_USAGE_RECORDS_TABLE}
(
    {BASE_BILLING_USAGE_RECORDS_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_BILLING_USAGE_RECORDS,
            group=CONSUMER_GROUP_BILLING_USAGE_RECORDS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_SHARED_NAMED_COLLECTION,
        )
    }
SETTINGS date_time_input_format = 'best_effort'
"""
