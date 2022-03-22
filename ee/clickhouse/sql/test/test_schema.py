import uuid

import pytest

from ee.clickhouse.sql.schema import CREATE_TABLE_QUERIES, KAFKA_EVENTS_TABLE_SQL, build_query, get_table_name

KAFKA_CREATE_TABLE_QUERIES = [query for query in CREATE_TABLE_QUERIES if "Kafka" in build_query(query)]
MERGE_TREE_TABLE_QUERIES = [query for query in CREATE_TABLE_QUERIES if "MergeTree" in build_query(query)]


@pytest.mark.parametrize("query", CREATE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query(query, snapshot, settings):
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
