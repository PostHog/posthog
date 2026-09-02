import re
import uuid
from collections.abc import Iterator

import pytest

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON, KAFKA_COLUMNS_WITH_PARTITION
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
    DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL,
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


def _column_definition_lines(block: str) -> Iterator[str]:
    for raw_line in block.splitlines():
        line = raw_line.strip().lstrip(",").strip()
        if not line or line.startswith("--") or line.startswith("INDEX "):
            continue
        yield line


def _declared_column_names(block: str) -> list[str]:
    return [line.split()[0] for line in _column_definition_lines(block)]


# Cuts a column definition down to its name and type, so a parenthesized type
# survives intact while a MATERIALIZED expression or a COMMENT is dropped.
_COLUMN_MODIFIER = re.compile(r"\s+(?:MATERIALIZED|DEFAULT|ALIAS|COMMENT|CODEC)\b")


def _flag_evaluations_table_columns(create_sql: str) -> list[str]:
    # Fail closed: without the anchor, rpartition would hand back the whole
    # statement and every caller would compare the same junk list, passing while
    # checking nothing.
    body, anchor, _ = create_sql.split("(", 1)[1].rpartition(")\nENGINE")
    assert anchor, f"no column list found in {create_sql[:60]!r}"
    return [_COLUMN_MODIFIER.split(line, maxsplit=1)[0] for line in _column_definition_lines(body)]


def _mv_projected_names(mv_sql: str) -> list[str]:
    projection = mv_sql.split("AS SELECT", 1)[1].split("\nFROM ", 1)[0]
    names: list[str] = []
    for raw_line in projection.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        names.append(line.rstrip(",").rsplit(" AS ", 1)[-1].strip())
    return names


def test_flag_evaluations_mv_projection_matches_column_template():
    # Every flag_evaluations table renders from one column template, but the MV
    # hand-writes its SELECT projection. Order matters as much as membership: the
    # MV writes to writable_flag_evaluations positionally, so a dropped or
    # reordered column lands data in the wrong column without raising.
    template_columns = _declared_column_names(FLAG_EVALUATIONS_KAFKA_COLUMNS)
    assert template_columns

    kafka_meta_columns = _declared_column_names(KAFKA_COLUMNS_WITH_PARTITION)
    assert _mv_projected_names(FLAG_EVALUATIONS_MV_SQL()) == template_columns + kafka_meta_columns


def test_flag_evaluations_read_table_declares_every_stored_column():
    # The typed property columns carry their DEFAULT expression on
    # sharded_flag_evaluations, which computes them, and are repeated as plain
    # columns on the Distributed read table, which computes nothing. Those two
    # lists are maintained by hand, so a column or a type changed in one and not
    # the other stays invisible until a query asks flag_evaluations for
    # something only the shards have.
    stored_columns = _flag_evaluations_table_columns(FLAG_EVALUATIONS_TABLE_SQL())
    assert stored_columns

    assert _flag_evaluations_table_columns(DISTRIBUTED_FLAG_EVALUATIONS_TABLE_SQL()) == stored_columns


@pytest.fixture(autouse=True)
def mock_uuid4(mocker):
    mock_uuid4 = mocker.patch("uuid.uuid4")
    mock_uuid4.return_value = uuid.UUID("77f1df52-4b43-11e9-910f-b8ca3a9b9f3e")
    yield mock_uuid4
