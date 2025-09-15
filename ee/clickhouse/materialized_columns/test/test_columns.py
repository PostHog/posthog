import datetime
from collections.abc import Iterable
from datetime import timedelta
from time import sleep

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest import TestCase
from unittest.mock import patch

from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns
from posthog.conftest import create_clickhouse_tables
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.property import PropertyName, TableColumn
from posthog.settings import CLICKHOUSE_DATABASE

from ee.clickhouse.materialized_columns.columns import (
    MaterializedColumn,
    MaterializedColumnDetails,
    backfill_materialized_columns,
    drop_column,
    get_enabled_materialized_columns,
    get_materialized_columns,
    materialize,
    update_column_is_disabled,
)

EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS = [f"$group_{i}" for i in range(GROUP_TYPES_LIMIT)] + [
    "$session_id",
    "$window_id",
]


class TestMaterializedColumnDetails(TestCase):
    def test_column_comment_formats(self):
        old_format_comment = "column_materializer::foo"
        old_format_details = MaterializedColumnDetails.from_column_comment(old_format_comment)
        assert old_format_details == MaterializedColumnDetails(
            "properties",  # the default
            "foo",
            is_disabled=False,
        )
        # old comment format is implicitly upgraded to the newer format when serializing
        assert old_format_details.as_column_comment() == "column_materializer::properties::foo"

        new_format_comment = "column_materializer::person_properties::bar"
        new_format_details = MaterializedColumnDetails.from_column_comment(new_format_comment)
        assert new_format_details == MaterializedColumnDetails(
            "person_properties",
            "bar",
            is_disabled=False,
        )
        assert new_format_details.as_column_comment() == new_format_comment

        new_format_disabled_comment = "column_materializer::person_properties::bar::disabled"
        new_format_disabled_details = MaterializedColumnDetails.from_column_comment(new_format_disabled_comment)
        assert new_format_disabled_details == MaterializedColumnDetails(
            "person_properties",
            "bar",
            is_disabled=True,
        )
        assert new_format_disabled_details.as_column_comment() == new_format_disabled_comment

        with pytest.raises(ValueError):
            MaterializedColumnDetails.from_column_comment("bad-prefix::property")

        with pytest.raises(ValueError):
            MaterializedColumnDetails.from_column_comment("bad-prefix::column::property")

        with pytest.raises(ValueError):
            MaterializedColumnDetails.from_column_comment("column_materializer::column::property::enabled")


class TestMaterializedColumns(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        self.recreate_database()
        return super().setUp()

    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def recreate_database(self):
        sync_execute(f"DROP DATABASE {CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {CLICKHOUSE_DATABASE}")
        create_clickhouse_tables()

    def test_get_columns_default(self):
        assert sorted([property_name for property_name, _ in get_materialized_columns("events")]) == sorted(
            EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS
        )
        assert sorted(get_materialized_columns("person")) == sorted([])

    def test_caching_and_materializing(self):
        base_time = datetime.datetime.fromisoformat("2020-01-04T13:01:01Z")
        with freeze_time(base_time):
            materialize("events", "$foo", create_minmax_index=True)
            materialize("events", "$bar", create_minmax_index=True)
            materialize("person", "$zeta", create_minmax_index=True)

            assert sorted(
                [
                    property_name
                    for property_name, _ in get_enabled_materialized_columns("events", use_cache=True).keys()
                ]
            ) == sorted(["$foo", "$bar", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS])
            assert sorted(get_enabled_materialized_columns("person", use_cache=True).keys()) == sorted(
                [("$zeta", "properties")]
            )

            materialize("events", "abc", create_minmax_index=True)

            assert sorted(
                [
                    property_name
                    for property_name, _ in get_enabled_materialized_columns("events", use_cache=True).keys()
                ]
            ) == sorted(["$foo", "$bar", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS])

        # The cache is updated in the background, so we need to poll for cache update with retry
        # otherwise this flakes
        @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=2), stop=stop_after_attempt(5))
        def check_cache_updated():
            assert sorted(
                [
                    property_name
                    for property_name, _ in get_enabled_materialized_columns("events", use_cache=True).keys()
                ]
            ) == sorted(["$foo", "$bar", "abc", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS])

        with freeze_time(base_time + timedelta(minutes=59)):
            check_cache_updated()

    @patch("secrets.choice", return_value="X")
    def test_materialized_column_naming(self, mock_choice):
        assert materialize("events", "$foO();--sqlinject", create_minmax_index=True).name == "mat_$foO_____sqlinject"

        mock_choice.return_value = "Y"
        assert (
            materialize("events", "$foO();ääsqlinject", create_minmax_index=True).name == "mat_$foO_____sqlinject_YYYY"
        )

        mock_choice.return_value = "Z"
        assert (
            materialize("events", "$foO_____sqlinject", create_minmax_index=True).name == "mat_$foO_____sqlinject_ZZZZ"
        )

        assert materialize("person", "SoMePrOp", create_minmax_index=True).name == "pmat_SoMePrOp"

    def test_backfilling_data(self):
        sync_execute("ALTER TABLE events DROP COLUMN IF EXISTS mat_prop")
        sync_execute("ALTER TABLE events DROP COLUMN IF EXISTS mat_another")

        _create_event(
            event="some_event",
            distinct_id="1",
            team=self.team,
            timestamp="2020-01-01 00:00:00",
            properties={"prop": 1},
        )
        _create_event(
            event="some_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"prop": 2, "another": 5},
        )
        _create_event(
            event="some_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"prop": 3},
        )
        _create_event(
            event="another_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-04 00:00:00",
        )
        _create_event(
            event="third_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"prop": 4},
        )
        _create_event(
            event="fourth_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-06 00:00:00",
            properties={"another": 6},
        )

        columns = [
            materialize("events", "prop", create_minmax_index=True),
            materialize("events", "another", create_minmax_index=True),
        ]

        assert self._count_materialized_rows("mat_prop") == 0
        assert self._count_materialized_rows("mat_another") == 0

        with freeze_time("2021-05-10T14:00:01Z"):
            backfill_materialized_columns(
                "events",
                columns,
                timedelta(days=50),
                test_settings={"mutations_sync": "0"},
            )

        _create_event(
            event="fifth_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-07 00:00:00",
            properties={"another": 7},
        )

        iterations = 0
        while self._get_count_of_mutations_running() > 0 and iterations < 100:
            sleep(0.1)
            iterations += 1

        assert self._count_materialized_rows("mat_prop") >= 4
        assert self._count_materialized_rows("mat_another") >= 4

        assert sync_execute("SELECT mat_prop, mat_another FROM events ORDER BY timestamp") == [
            ("1", ""),
            ("2", "5"),
            ("3", ""),
            ("", ""),
            ("4", ""),
            ("", "6"),
            ("", "7"),
        ]

    def test_column_types(self):
        columns = [
            materialize("events", "myprop", create_minmax_index=True),
            materialize("events", "myprop_nullable", create_minmax_index=True, is_nullable=True),
        ]

        expr_nonnullable = "replaceRegexpAll(JSONExtractRaw(properties, 'myprop'), '^\"|\"$', '')"
        expr_nullable = "JSONExtract(properties, 'myprop_nullable', 'Nullable(String)')"

        backfill_materialized_columns("events", columns, timedelta(days=50))
        assert self._get_column_types("mat_myprop") == ("String", "DEFAULT", expr_nonnullable)
        assert self._get_column_types("mat_myprop_nullable") == ("Nullable(String)", "DEFAULT", expr_nullable)

    def _count_materialized_rows(self, column):
        return sync_execute(
            """
            SELECT sum(rows)
            FROM system.parts_columns
            WHERE database = %(database)s
              AND table = %(table)s
              AND column = %(column)s
        """,
            {
                "database": CLICKHOUSE_DATABASE,
                "table": EVENTS_DATA_TABLE(),
                "column": column,
            },
        )[0][0]

    def _get_count_of_mutations_running(self) -> int:
        return sync_execute(
            """
            SELECT count(*)
            FROM system.mutations
            WHERE is_done = 0
        """
        )[0][0]

    def _get_column_types(self, column: str):
        return sync_execute(
            """
            SELECT type, default_kind, default_expression
            FROM system.columns
            WHERE database = %(database)s AND table = %(table)s AND name = %(column)s
            """,
            {
                "database": CLICKHOUSE_DATABASE,
                "table": EVENTS_DATA_TABLE(),
                "column": column,
            },
        )[0]

    def test_lifecycle(self):
        table: TablesWithMaterializedColumns = "events"
        property_names = ["foo", "bar"]
        source_column: TableColumn = "properties"

        # create materialized columns
        materialized_columns = {}
        for property_name in property_names:
            materialized_columns[property_name] = materialize(
                table, property_name, table_column=source_column, create_minmax_index=True
            ).name

        assert set(property_names) == materialized_columns.keys()

        # ensure they exist everywhere
        for property_name, destination_column in materialized_columns.items():
            key = (property_name, source_column)
            assert get_materialized_columns(table)[key].name == destination_column
            assert MaterializedColumn.get(table, destination_column) == MaterializedColumn(
                destination_column,
                MaterializedColumnDetails(source_column, property_name, is_disabled=False),
                is_nullable=False,
            )

        # disable them and ensure updates apply as needed
        update_column_is_disabled(table, materialized_columns.values(), is_disabled=True)
        for property_name, destination_column in materialized_columns.items():
            key = (property_name, source_column)
            assert get_materialized_columns(table)[key].name == destination_column
            assert MaterializedColumn.get(table, destination_column) == MaterializedColumn(
                destination_column,
                MaterializedColumnDetails(source_column, property_name, is_disabled=True),
                is_nullable=False,
            )

        # re-enable them and ensure updates apply as needed
        update_column_is_disabled(table, materialized_columns.values(), is_disabled=False)
        for property_name, destination_column in materialized_columns.items():
            key = (property_name, source_column)
            assert get_materialized_columns(table)[key].name == destination_column
            assert MaterializedColumn.get(table, destination_column) == MaterializedColumn(
                destination_column,
                MaterializedColumnDetails(source_column, property_name, is_disabled=False),
                is_nullable=False,
            )

        # drop them and ensure updates apply as needed
        drop_column(table, materialized_columns.values())
        for property_name, destination_column in materialized_columns.items():
            key = (property_name, source_column)
            assert key not in get_materialized_columns(table)
            with pytest.raises(ValueError):
                MaterializedColumn.get(table, destination_column)

    def _get_latest_mutation_id(self, table: str) -> str:
        [(mutation_id,)] = sync_execute(
            """
            SELECT max(mutation_id)
            FROM system.mutations
            WHERE
                database = currentDatabase()
                AND table = %(table)s
            """,
            {"table": table},
        )
        return mutation_id

    def _get_mutations_since_id(self, table: str, id: str) -> Iterable[str]:
        return [
            command
            for (command,) in sync_execute(
                """
                SELECT command
                FROM system.mutations
                WHERE
                    database = currentDatabase()
                    AND table = %(table)s
                    AND mutation_id > %(mutation_id)s
                ORDER BY mutation_id
                """,
                {"table": table, "mutation_id": id},
            )
        ]

    def test_drop_optimized_no_index(self):
        table: TablesWithMaterializedColumns = (
            "person"  # little bit easier than events because no shard awareness needed
        )
        property: PropertyName = "myprop"
        source_column: TableColumn = "properties"

        destination_column = materialize(table, property, table_column=source_column, create_minmax_index=False)

        latest_mutation_id_before_drop = self._get_latest_mutation_id(table)

        drop_column(table, destination_column.name)

        mutations_ran = self._get_mutations_since_id(table, latest_mutation_id_before_drop)
        assert not any("DROP INDEX" in mutation for mutation in mutations_ran)

    def test_drop_optimized_no_column(self):
        table: TablesWithMaterializedColumns = (
            "person"  # little bit easier than events because no shard awareness needed
        )
        property: PropertyName = "myprop"
        source_column: TableColumn = "properties"

        # create the materialized column
        destination_column = materialize(table, property, table_column=source_column, create_minmax_index=False)

        sync_execute(f"ALTER TABLE {table} DROP COLUMN {destination_column.name}", settings={"alter_sync": 1})

        latest_mutation_id_before_drop = self._get_latest_mutation_id(table)

        drop_column(table, destination_column.name)

        mutations_ran = self._get_mutations_since_id(table, latest_mutation_id_before_drop)
        assert not any("DROP COLUMN" in mutation for mutation in mutations_ran)
