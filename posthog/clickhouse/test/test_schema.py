import re
import uuid

import pytest

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON
from posthog.clickhouse.schema import (
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_TABLE_QUERIES,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    build_query,
    get_table_name,
)
from posthog.models.event.sql import (
    EVENTS_JSON_TABLE_MV_SQL,
    KAFKA_EVENTS_NATIVE_JSON_TABLE,
    KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL,
)
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_KAFKA_COLUMNS,
    FLAG_EVALUATIONS_MV_SQL,
    FLAG_EVALUATIONS_TABLE_SQL,
)


@pytest.mark.parametrize("query", CREATE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query(query, snapshot, settings):
    settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA = False

    assert build_query(query) == snapshot


@pytest.mark.parametrize("query", CREATE_MERGETREE_TABLE_QUERIES, ids=get_table_name)
def test_create_table_query_replicated_and_storage(query, snapshot, settings):
    settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA = False
    settings.CLICKHOUSE_ENABLE_STORAGE_POLICY = True

    assert build_query(query) == snapshot


@pytest.mark.parametrize("query", CREATE_KAFKA_TABLE_QUERIES, ids=get_table_name)
def test_create_kafka_table_with_different_kafka_host(query, snapshot):
    # Historical name; the override that used to drive `KAFKA_HOSTS_FOR_CLICKHOUSE`
    # was removed because every Kafka table now renders via a named collection.
    assert build_query(query) == snapshot


def test_create_kafka_events_with_disabled_protobuf(snapshot, settings):
    assert KAFKA_EVENTS_TABLE_JSON_SQL() == snapshot


def test_events_json_table_uses_dedicated_kafka_consumer_group(settings):
    kafka_table_query = KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL(on_cluster=False)
    mv_query = EVENTS_JSON_TABLE_MV_SQL(on_cluster=False)

    assert f"CREATE TABLE IF NOT EXISTS {KAFKA_EVENTS_NATIVE_JSON_TABLE}" in kafka_table_query
    assert f"kafka_group_name = '{CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON}'" in kafka_table_query
    assert f"FROM {settings.CLICKHOUSE_DATABASE}.{KAFKA_EVENTS_NATIVE_JSON_TABLE}" in mv_query


def test_flag_evaluations_column_lists_stay_in_sync():
    # The shared column template is the canonical column list for the Kafka
    # and Distributed tables. The sharded data table inlines its own copy (to
    # carry CODEC/INDEX/DEFAULT annotations) and the MV hand-writes its SELECT
    # projection, so both must be updated by hand whenever a column is added
    # or removed here. A column present in the shared list but missing from
    # one of the other two would silently drop data on the write path (MV) or
    # mismatch the Distributed/local table shape (sharded table), neither of
    # which raises an error at creation time.
    column_names = {line.strip().split()[0] for line in FLAG_EVALUATIONS_KAFKA_COLUMNS.strip().splitlines()}
    assert column_names

    sharded_table_sql = FLAG_EVALUATIONS_TABLE_SQL()
    mv_sql = FLAG_EVALUATIONS_MV_SQL()

    for name in column_names:
        pattern = rf"\b{re.escape(name)}\b"
        assert re.search(pattern, sharded_table_sql), (
            f"{name!r} is in the shared column list but missing from the sharded data table's DDL"
        )
        assert re.search(pattern, mv_sql), f"{name!r} is in the shared column list but not projected by the MV"


@pytest.fixture(autouse=True)
def mock_uuid4(mocker):
    mock_uuid4 = mocker.patch("uuid.uuid4")
    mock_uuid4.return_value = uuid.UUID("77f1df52-4b43-11e9-910f-b8ca3a9b9f3e")
    yield mock_uuid4
