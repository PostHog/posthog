# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!
from typing import Literal

from django.conf import settings
from django.forms import ValidationError

STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

CLICKHOUSE_SUPPORTED_INTERVAL_UNITS = ["SECOND", "MINUTE", "HOUR", "DAY", "WEEK", "MONTH", "QUARTER", "YEAR"]

KAFKA_ENGINE = "Kafka('{kafka_host}', '{topic}', '{group}', '{serialization}')"

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


def kafka_engine(
    topic: str,
    kafka_host=None,
    group="group1",
    serialization: Literal["JSONEachRow", "Protobuf"] = "JSONEachRow",
    proto_schema=None,
    skip_broken_messages=100,
):
    if kafka_host is None:
        kafka_host = settings.KAFKA_HOSTS_FOR_CLICKHOUSE
    if serialization == "Protobuf" and not settings.CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS:
        return KAFKA_PROTO_ENGINE.format(
            topic=topic,
            kafka_host=kafka_host,
            group=group,
            proto_schema=proto_schema,
            skip_broken_messages=skip_broken_messages,
        )
    else:
        return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization="JSONEachRow")


def ttl_period(field: str = "created_at", value: int = 3, interval_unit: str = "WEEK"):
    if settings.TEST:
        return ""

    if interval_unit not in CLICKHOUSE_SUPPORTED_INTERVAL_UNITS:
        supported_units_str = ", ".join(CLICKHOUSE_SUPPORTED_INTERVAL_UNITS)
        raise ValidationError(f"interval_unit in ttl_period must be one of {supported_units_str}")

    date = f"{field}"

    if interval_unit not in ["SECOND", "MINUTE", "HOUR"]:
        date = f"toDate({field})"

    return "" if settings.TEST else f"TTL {date} + INTERVAL {value} {interval_unit}"


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"
