import importlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from django.conf import settings as django_settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseCredentials, ClickHouseUser, NodeRole
from posthog.clickhouse.schema import (
    CREATE_DICTIONARY_QUERIES,
    CREATE_DISTRIBUTED_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    get_table_name,
)
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
    WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE,
)

MIGRATION = "posthog.clickhouse.migrations.0343_person_group_membership"


def test_dictionary_sql(snapshot, mocker, settings) -> None:
    settings.CLICKHOUSE_DATABASE = "posthog"
    creds = mocker.patch(
        "posthog.models.person_group_membership.sql.get_clickhouse_creds",
        return_value=ClickHouseCredentials(user="dict_reader", password="fake'password\\with_escape"),
    )
    assert PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY_SQL() == snapshot
    creds.assert_called_once_with(ClickHouseUser.DICT_READER)


@pytest.mark.parametrize("deployment", ["", "DEV", "US", "EU"])
@pytest.mark.parametrize("multinode", [False, True])
def test_migration_placement(deployment: str, multinode: bool) -> None:
    module = importlib.import_module(MIGRATION)
    try:
        with patch.multiple("posthog.settings", CLOUD_DEPLOYMENT=deployment, MULTINODE_CLICKHOUSE=multinode):
            operations = importlib.reload(module).operations
            expected_roles = [
                [NodeRole.AUX],
                [NodeRole.AUX],
                [NodeRole.DATA, NodeRole.INGESTION_SMALL],
                [NodeRole.DATA],
                [NodeRole.INGESTION_SMALL],
                [NodeRole.INGESTION_SMALL],
            ]
            assert [op._node_roles for op in operations] == expected_roles
            assert [op._effective_node_roles for op in operations] == (
                expected_roles if deployment or multinode else [[NodeRole.ALL]] * 6
            )
            for op in operations:
                assert "ON CLUSTER" not in op._sql
                assert "IF NOT EXISTS" in op._sql
                assert "Kafka" not in op._sql
                assert "MATERIALIZED VIEW" not in op._sql
    finally:
        importlib.reload(module)


@pytest.mark.parametrize(
    "queries,expected",
    [
        (
            CREATE_MERGETREE_TABLE_QUERIES,
            {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE, PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE},
        ),
        (
            CREATE_DISTRIBUTED_TABLE_QUERIES,
            {
                PERSON_GROUP_MEMBERSHIP_TABLE,
                WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE,
                DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
            },
        ),
        (CREATE_DICTIONARY_QUERIES, {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}),
    ],
    ids=["storage", "proxies", "dictionary"],
)
def test_local_schema_includes_membership_objects(
    queries: tuple[str | Callable[[], str], ...], expected: set[str]
) -> None:
    assert expected <= {get_table_name(query) for query in queries}


@pytest.fixture
def membership_schema(clickhouse_database) -> Iterator[None]:
    module = importlib.reload(importlib.import_module(MIGRATION))
    for _ in range(2):
        for operation in module.operations:
            sync_execute(operation._sql)
    try:
        for table in (SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE, PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE):
            sync_execute(f"TRUNCATE TABLE {table}")
        sync_execute(f"SYSTEM RELOAD DICTIONARY {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}")
        yield
    finally:
        for table in (SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE, PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE):
            sync_execute(f"TRUNCATE TABLE {table}")
        sync_execute(f"SYSTEM RELOAD DICTIONARY {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}")


@pytest.mark.usefixtures("membership_schema")
def test_empty_schema_engines_and_keys() -> None:
    rows = sync_execute(
        """SELECT name, engine, sorting_key, engine_full, create_table_query
        FROM system.tables WHERE database = %(database)s AND name IN %(tables)s""",
        {
            "database": django_settings.CLICKHOUSE_DATABASE,
            "tables": (
                SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
                PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
                PERSON_GROUP_MEMBERSHIP_TABLE,
                WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE,
                DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
                PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY,
            ),
        },
    )
    tables = {row[0]: row[1:] for row in rows}
    assert len(tables) == 6
    storage = tables[SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE]
    assert storage[0] == "ReplicatedAggregatingMergeTree"
    assert storage[1] == "team_id, group_type_index, group_key, distinct_id"
    assert "min_rows_for_wide_part = 0" in storage[3]
    assert "min_bytes_for_wide_part = 0" in storage[3]
    assert sync_execute(
        """SELECT expr, type_full, granularity FROM system.data_skipping_indices
        WHERE database = %(database)s AND table = %(table)s""",
        {"database": django_settings.CLICKHOUSE_DATABASE, "table": SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE},
    ) == [("distinct_id", "bloom_filter(0.01)", 1)]
    config = tables[PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE]
    assert config[0] == "ReplicatedReplacingMergeTree"
    assert config[1] == "team_id"
    assert ", version)" in config[2]
    for table in (PERSON_GROUP_MEMBERSHIP_TABLE, WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE):
        engine = tables[table]
        assert engine[0] == "Distributed"
        assert f"'{django_settings.CLICKHOUSE_AUX_CLUSTER}'" in engine[2]
        assert "sipHash64(team_id, group_type_index, group_key)" in engine[2]
        assert sync_execute(f"SELECT count() FROM {table}") == [(0,)]
    assert sync_execute(f"SELECT count() FROM {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}") == [(0,)]


@pytest.mark.usefixtures("membership_schema")
def test_dictionary_uses_latest_valid_enabled_config() -> None:
    rows = [
        (1001, 0, 1, 1),
        (1002, 4, 1, 1),
        (1003, 5, 1, 1),
        (1004, 255, 1, 1),
        (1005, 0, 0, 1),
        (1006, 0, 1, 1),
        (1006, 0, 0, 2),
        (1007, 0, 1, 1),
        (1007, 5, 1, 2),
        (1008, 2, 1, 3),
        (1008, 0, 1, 1),
        (1008, 4, 1, 2),
        (1009, 5, 0, 1),
        (1009, 3, 1, 2),
    ]
    sync_execute(f"SYSTEM STOP MERGES {PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}")
    try:
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE} VALUES",
            rows,
            settings={"distributed_foreground_insert": 1},
        )
        sync_execute(f"SYSTEM RELOAD DICTIONARY {PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}")
        result = sync_execute(
            f"""SELECT team_id,
                dictHas('{PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}', tuple(team_id)),
                dictGet('{PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}', 'group_type_index', tuple(team_id)),
                dictGet('{PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}', 'enabled', tuple(team_id))
            FROM (SELECT toInt64(arrayJoin(range(1000, 1010))) AS team_id) ORDER BY team_id"""
        )
        assert result == [
            (1000, 0, 255, 0),
            (1001, 1, 0, 1),
            (1002, 1, 4, 1),
            (1003, 0, 255, 0),
            (1004, 0, 255, 0),
            (1005, 0, 255, 0),
            (1006, 0, 255, 0),
            (1007, 0, 255, 0),
            (1008, 1, 2, 1),
            (1009, 1, 3, 1),
        ]
    finally:
        sync_execute(f"SYSTEM START MERGES {PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE}")


@pytest.mark.usefixtures("membership_schema")
def test_distributed_writes_and_reads_aggregate_overlap() -> None:
    for table, first_seen, last_seen in [
        (WRITABLE_PERSON_GROUP_MEMBERSHIP_TABLE, "2024-01-02 00:00:00.123456", "2024-01-04 00:00:00.654321"),
        (PERSON_GROUP_MEMBERSHIP_TABLE, "2024-01-01 00:00:00.123456", "2024-01-03 00:00:00.654321"),
    ]:
        sync_execute(
            f"""INSERT INTO {table}
            SELECT 1001, 0, 'example-account', 'example-distinct-id',
                toDateTime64(%(first_seen)s, 6, 'UTC'), toDateTime64(%(last_seen)s, 6, 'UTC')""",
            {"first_seen": first_seen, "last_seen": last_seen},
            settings={"distributed_foreground_insert": 1},
        )
    assert sync_execute(
        f"""SELECT team_id, group_type_index, group_key, distinct_id, min(first_seen), max(last_seen)
        FROM {PERSON_GROUP_MEMBERSHIP_TABLE} GROUP BY team_id, group_type_index, group_key, distinct_id"""
    ) == [
        (
            1001,
            0,
            "example-account",
            "example-distinct-id",
            datetime(2024, 1, 1, microsecond=123456, tzinfo=UTC),
            datetime(2024, 1, 4, microsecond=654321, tzinfo=UTC),
        )
    ]


@pytest.mark.parametrize("lightweight", [False, True], ids=["mutation", "lightweight"])
@pytest.mark.usefixtures("membership_schema")
def test_storage_supports_distinct_id_and_team_deletion(lightweight: bool) -> None:
    sync_execute(
        f"""INSERT INTO {PERSON_GROUP_MEMBERSHIP_TABLE}
        SELECT team_id, 0, group_key, distinct_id, now64(6, 'UTC'), now64(6, 'UTC')
        FROM values('team_id Int64, group_key String, distinct_id String',
            (1001, 'account-a', 'person-a'), (1001, 'account-b', 'person-a'),
            (1001, 'account-a', 'person-b'), (1002, 'account-a', 'person-a'))""",
        settings={"distributed_foreground_insert": 1},
    )
    for predicate, expected in [
        ("team_id = 1001 AND distinct_id = 'person-a'", [(1001, "person-b"), (1002, "person-a")]),
        ("team_id = 1001", [(1002, "person-a")]),
    ]:
        sql = (
            f"DELETE FROM {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE} WHERE {predicate}"
            if lightweight
            else f"ALTER TABLE {SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE} DELETE WHERE {predicate}"
        )
        sync_execute(sql, settings={"mutations_sync": 2, "lightweight_deletes_sync": 2})
        assert (
            sync_execute(
                f"SELECT team_id, distinct_id FROM {PERSON_GROUP_MEMBERSHIP_TABLE} ORDER BY team_id, distinct_id"
            )
            == expected
        )
