import re
import uuid

import pytest

from posthog.clickhouse.schema import (
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_TABLE_QUERIES,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    build_query,
    get_table_name,
)


def _normalize_xdist_suffix(query: str) -> str:
    """Normalize xdist worker suffixes in table/topic names for consistent snapshots"""
    # normalize database names (posthog_test_gw0 -> posthog_test)
    query = re.sub(r"posthog_test_gw\d+", "posthog_test", query)
    # normalize Kafka topic names (clickhouse_events_json_test_gw0 -> clickhouse_events_json_test)
    query = re.sub(r"_test_gw\d+", "_test", query)
    return query


@pytest.mark.parametrize("query", CREATE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query(query, snapshot):
    assert _normalize_xdist_suffix(build_query(query)) == snapshot


@pytest.mark.parametrize("query", CREATE_MERGETREE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query_replicated_and_storage(query, snapshot, settings):
    settings.CLICKHOUSE_ENABLE_STORAGE_POLICY = True

    assert _normalize_xdist_suffix(build_query(query)) == snapshot


@pytest.mark.parametrize("query", CREATE_KAFKA_TABLE_QUERIES, ids=get_table_name)
def test_create_kafka_table_with_different_kafka_host(query, snapshot, settings):
    settings.KAFKA_HOSTS_FOR_CLICKHOUSE = ["test.kafka.broker:9092"]

    assert _normalize_xdist_suffix(build_query(query)) == snapshot


def test_create_kafka_events_with_disabled_protobuf(snapshot, settings):
    assert _normalize_xdist_suffix(KAFKA_EVENTS_TABLE_JSON_SQL()) == snapshot


@pytest.fixture(autouse=True)
def mock_uuid4(mocker):
    mock_uuid4 = mocker.patch("uuid.uuid4")
    mock_uuid4.return_value = uuid.UUID("77f1df52-4b43-11e9-910f-b8ca3a9b9f3e")
    yield mock_uuid4
