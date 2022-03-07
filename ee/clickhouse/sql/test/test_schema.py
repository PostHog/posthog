import re
import uuid

import pytest

from ee.clickhouse.sql.cohort import *
from ee.clickhouse.sql.dead_letter_queue import *
from ee.clickhouse.sql.events import *
from ee.clickhouse.sql.groups import *
from ee.clickhouse.sql.person import *
from ee.clickhouse.sql.plugin_log_entries import *
from ee.clickhouse.sql.session_recording_events import *

CREATE_TABLE_QUERIES = [
    CREATE_COHORTPEOPLE_TABLE_SQL,
    PERSON_STATIC_COHORT_TABLE_SQL,
    DEAD_LETTER_QUEUE_TABLE_SQL,
    DEAD_LETTER_QUEUE_TABLE_MV_SQL,
    KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL,
    EVENTS_TABLE_SQL,
    KAFKA_EVENTS_TABLE_SQL,
    EVENTS_TABLE_MV_SQL,
    GROUPS_TABLE_SQL,
    KAFKA_GROUPS_TABLE_SQL,
    GROUPS_TABLE_MV_SQL,
    PERSONS_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSONS_TABLE_MV_SQL,
    PERSONS_DISTINCT_ID_TABLE_SQL,
    KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL,
    PERSONS_DISTINCT_ID_TABLE_MV_SQL,
    PERSON_DISTINCT_ID2_TABLE_SQL,
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    PERSON_DISTINCT_ID2_MV_SQL,
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    WRITABLE_EVENTS_TABLE_SQL,
    DISTRIBUTED_EVENTS_TABLE_SQL,
    WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
]

build_query = lambda query: query if isinstance(query, str) else query()
get_table_name = lambda query: re.findall(r" ([a-z0-9_]+) ON CLUSTER", build_query(query))[0]
KAFKA_CREATE_TABLE_QUERIES = [query for query in CREATE_TABLE_QUERIES if "Kafka" in build_query(query)]
MERGE_TREE_TABLE_QUERIES = [query for query in CREATE_TABLE_QUERIES if "MergeTree" in build_query(query)]


@pytest.mark.parametrize("query", CREATE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query(query, snapshot):
    settings.CLICKHOUSE_REPLICATION = False

    assert build_query(query) == snapshot


@pytest.mark.parametrize("query", MERGE_TREE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query_replicated_and_storage(query, snapshot, settings):
    settings.CLICKHOUSE_REPLICATION = True
    settings.CLICKHOUSE_ENABLE_STORAGE_POLICY = True

    assert build_query(query) == snapshot


@pytest.mark.parametrize("query", KAFKA_CREATE_TABLE_QUERIES, ids=get_table_name)
def test_create_kafka_table_with_different_kafka_host(query, snapshot, settings):
    settings.KAFKA_HOSTS_FOR_CLICKHOUSE = "test.kafka.broker:9092"

    assert build_query(query) == snapshot


def test_create_kafka_events_with_disabled_protobuf(snapshot, settings):
    settings.CLICKHOUSE_DISABLE_EXTERNAL_SCHEMAS = True

    assert KAFKA_EVENTS_TABLE_SQL() == snapshot


@pytest.fixture(autouse=True)
def mock_uuid4(mocker):
    mock_uuid4 = mocker.patch("uuid.uuid4")
    mock_uuid4.return_value = uuid.UUID("77f1df52-4b43-11e9-910f-b8ca3a9b9f3e")
    yield mock_uuid4
