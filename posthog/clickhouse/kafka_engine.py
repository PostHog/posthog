# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!

from django.conf import settings

STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

COPY_ROWS_BETWEEN_TEAMS_BASE_SQL = """
INSERT INTO {table_name} (team_id, {columns_except_team_id}) SELECT %(target_team_id)s, {columns_except_team_id}
FROM {table_name} WHERE team_id = %(source_team_id)s
"""

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
    topic: str, kafka_host=None, group="group1",
):
    if kafka_host is None:
        kafka_host = settings.KAFKA_HOSTS_FOR_CLICKHOUSE
    return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization="JSONEachRow")


def ttl_period(field: str = "created_at", weeks: int = 3):
    return "" if settings.TEST else f"TTL toDate({field}) + INTERVAL {weeks} WEEK"


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"
