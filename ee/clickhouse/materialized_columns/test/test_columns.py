from datetime import timedelta
from time import sleep
from unittest import TestCase
from unittest.mock import patch

from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import (
    MaterializedColumn,
    MaterializedColumnDetails,
    backfill_materialized_columns,
    drop_column,
    get_materialized_columns,
    materialize,
    update_column_is_disabled,
)
from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_enabled_materialized_columns
from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.property import PropertyName, TableColumn
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

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

        with self.assertRaises(ValueError):
            MaterializedColumnDetails.from_column_comment("bad-prefix::property")

        with self.assertRaises(ValueError):
            MaterializedColumnDetails.from_column_comment("bad-prefix::column::property")

        with self.assertRaises(ValueError):
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
        create_clickhouse_tables(0)

    def test_get_columns_default(self):
        self.assertCountEqual(
            [property_name for property_name, _ in get_materialized_columns("events")],
            EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS,
        )
        self.assertCountEqual(get_materialized_columns("person"), [])

    def test_caching_and_materializing(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            materialize("events", "$foo", create_minmax_index=True)
            materialize("events", "$bar", create_minmax_index=True)
            materialize("person", "$zeta", create_minmax_index=True)

            self.assertCountEqual(
                [
                    property_name
                    for property_name, _ in get_enabled_materialized_columns("events", use_cache=True).keys()
                ],
                ["$foo", "$bar", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS],
            )
            self.assertCountEqual(
                get_enabled_materialized_columns("person", use_cache=True).keys(),
                [("$zeta", "properties")],
            )

            materialize("events", "abc", create_minmax_index=True)

            self.assertCountEqual(
                [
                    property_name
                    for property_name, _ in get_enabled_materialized_columns("events", use_cache=True).keys()
                ],
                ["$foo", "$bar", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS],
            )

        with freeze_time("2020-01-04T14:00:01Z"):
            self.assertCountEqual(
                [
                    property_name
                    for property_name, _ in get_enabled_materialized_columns("events", use_cache=True).keys()
                ],
                ["$foo", "$bar", "abc", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS],
            )

    @patch("secrets.choice", return_value="X")
    def test_materialized_column_naming(self, mock_choice):
        materialize("events", "$foO();--sqlinject", create_minmax_index=True)
        mock_choice.return_value = "Y"
        materialize("events", "$foO();ääsqlinject", create_minmax_index=True)
        mock_choice.return_value = "Z"
        materialize("events", "$foO_____sqlinject", create_minmax_index=True)
        materialize("person", "SoMePrOp", create_minmax_index=True)

        self.assertDictContainsSubset(
            {
                ("$foO();--sqlinject", "properties"): "mat_$foO_____sqlinject",
                ("$foO();ääsqlinject", "properties"): "mat_$foO_____sqlinject_YYYY",
                ("$foO_____sqlinject", "properties"): "mat_$foO_____sqlinject_ZZZZ",
            },
            get_materialized_columns("events"),
        )

        self.assertEqual(
            get_materialized_columns("person"),
            {("SoMePrOp", "properties"): "pmat_SoMePrOp"},
        )

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

        materialize("events", "prop", create_minmax_index=True)
        materialize("events", "another", create_minmax_index=True)

        self.assertEqual(self._count_materialized_rows("mat_prop"), 0)
        self.assertEqual(self._count_materialized_rows("mat_another"), 0)

        with freeze_time("2021-05-10T14:00:01Z"):
            backfill_materialized_columns(
                "events",
                [("prop", "properties"), ("another", "properties")],
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

        self.assertGreaterEqual(self._count_materialized_rows("mat_prop"), 4)
        self.assertGreaterEqual(self._count_materialized_rows("mat_another"), 4)

        self.assertEqual(
            sync_execute("SELECT mat_prop, mat_another FROM events ORDER BY timestamp"),
            [
                ("1", ""),
                ("2", "5"),
                ("3", ""),
                ("", ""),
                ("4", ""),
                ("", "6"),
                ("", "7"),
            ],
        )

    def test_column_types(self):
        materialize("events", "myprop", create_minmax_index=True)

        expr = "replaceRegexpAll(JSONExtractRaw(properties, 'myprop'), '^\"|\"$', '')"
        self.assertEqual(("MATERIALIZED", expr), self._get_column_types("mat_myprop"))

        backfill_materialized_columns("events", [("myprop", "properties")], timedelta(days=50))
        self.assertEqual(("DEFAULT", expr), self._get_column_types("mat_myprop"))

        try:
            from ee.tasks.materialized_columns import mark_all_materialized
        except ImportError:
            pass
        else:
            mark_all_materialized()
            self.assertEqual(("MATERIALIZED", expr), self._get_column_types("mat_myprop"))

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
            SELECT default_kind, default_expression
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
        property: PropertyName = "myprop"
        source_column: TableColumn = "properties"

        # create the materialized column
        destination_column = materialize(table, property, table_column=source_column, create_minmax_index=True)
        assert destination_column is not None

        # ensure it exists everywhere
        key = (property, source_column)
        assert get_materialized_columns(table)[key] == destination_column
        assert MaterializedColumn.get(table, destination_column) == MaterializedColumn(
            destination_column,
            MaterializedColumnDetails(source_column, property, is_disabled=False),
        )

        # disable it and ensure updates apply as needed
        update_column_is_disabled(table, destination_column, is_disabled=True)
        assert get_materialized_columns(table)[key] == destination_column
        assert key not in get_materialized_columns(table, exclude_disabled_columns=True)
        assert MaterializedColumn.get(table, destination_column) == MaterializedColumn(
            destination_column,
            MaterializedColumnDetails(source_column, property, is_disabled=True),
        )

        # re-enable it and ensure updates apply as needed
        update_column_is_disabled(table, destination_column, is_disabled=False)
        assert get_materialized_columns(table, exclude_disabled_columns=False)[key] == destination_column
        assert get_materialized_columns(table, exclude_disabled_columns=True)[key] == destination_column
        assert MaterializedColumn.get(table, destination_column) == MaterializedColumn(
            destination_column,
            MaterializedColumnDetails(source_column, property, is_disabled=False),
        )

        # drop it and ensure updates apply as needed
        drop_column(table, destination_column)
        assert key not in get_materialized_columns(table, exclude_disabled_columns=False)
        assert key not in get_materialized_columns(table, exclude_disabled_columns=True)
        with self.assertRaises(ValueError):
            MaterializedColumn.get(table, destination_column)
