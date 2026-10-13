from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine
from posthog.clickhouse.table_engines import Distributed
from posthog.kafka_client.topics import KAFKA_DEAD_LETTER_QUEUE
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.settings.data_stores import CLICKHOUSE_SINGLE_SHARD_CLUSTER

# We pipe our Kafka dead letter queue into CH for easier analysis and longer retention
# This allows us to explore errors and replay events with ease

DEAD_LETTER_QUEUE_TABLE = "events_dead_letter_queue"


INSERT_DEAD_LETTER_QUEUE_EVENT_SQL = """
INSERT INTO events_dead_letter_queue
SELECT
%(id)s,
%(event_uuid)s,
%(event)s,
%(properties)s,
%(distinct_id)s,
%(team_id)s,
%(elements_chain)s,
%(created_at)s,
%(ip)s,
%(site_url)s,
%(now)s,
%(raw_payload)s,
%(error_timestamp)s,
%(error_location)s,
%(error)s,
['some_tag'],
0,
now()
"""

DEAD_LETTER_QUEUE_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    id UUID,
    event_uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    distinct_id VARCHAR,
    team_id Int64,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    ip VARCHAR,
    site_url VARCHAR,
    now DateTime64(6, 'UTC'),
    raw_payload VARCHAR,
    error_timestamp DateTime64(6, 'UTC'),
    error_location VARCHAR,
    error VARCHAR,
    tags Array(VARCHAR)
    {extra_fields}
) ENGINE = {engine}
"""

# skip up to 1000 messages per block. blocks can be as large as 65505
# if a block has >1000 broken messages it probably means we're doing something wrong
# so it should fail and require manual intervention


def KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL(on_cluster=True):
    return (DEAD_LETTER_QUEUE_TABLE_BASE_SQL + " SETTINGS kafka_skip_broken_messages=1000").format(
        table_name="kafka_" + DEAD_LETTER_QUEUE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_DEAD_LETTER_QUEUE),
        extra_fields="",
    )


def WRITABLE_DEAD_LETTER_QUEUE_TABLE_SQL(on_cluster=True):
    return (DEAD_LETTER_QUEUE_TABLE_BASE_SQL).format(
        table_name="writable_" + DEAD_LETTER_QUEUE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(data_table=DEAD_LETTER_QUEUE_TABLE, cluster=CLICKHOUSE_SINGLE_SHARD_CLUSTER),
        extra_fields=f"""
    {KAFKA_COLUMNS}
    """,
    )


def DEAD_LETTER_QUEUE_TABLE_MV_SQL(target_table=f"writable_{DEAD_LETTER_QUEUE_TABLE}", on_cluster=True):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv {on_cluster_clause}
TO {database}.{target_table}
AS SELECT
id,
event_uuid,
event,
properties,
distinct_id,
team_id,
elements_chain,
created_at,
ip,
site_url,
now,
raw_payload,
error_timestamp,
error_location,
error,
tags,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
        table_name=DEAD_LETTER_QUEUE_TABLE,
        database=CLICKHOUSE_DATABASE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        target_table=target_table,
    )
