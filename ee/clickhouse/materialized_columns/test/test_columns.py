import random
from datetime import timedelta
from time import sleep

from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import (
    backfill_materialized_columns,
    get_materialized_columns,
    materialize,
)
from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.constants import GROUP_TYPES_LIMIT
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS = [f"$group_{i}" for i in range(GROUP_TYPES_LIMIT)] + [
    "$session_id",
    "$window_id",
]


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
        self.assertCountEqual(get_materialized_columns("events"), EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS)
        self.assertCountEqual(get_materialized_columns("person"), [])
        self.assertEqual(
            get_materialized_columns("session_recording_events"), {"has_full_snapshot": "has_full_snapshot"}
        )

    def test_caching_and_materializing(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            materialize("events", "$foo")
            materialize("events", "$bar")
            materialize("person", "$zeta")

            self.assertCountEqual(
                get_materialized_columns("events", use_cache=True).keys(),
                ["$foo", "$bar", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS],
            )
            self.assertCountEqual(get_materialized_columns("person", use_cache=True).keys(), ["$zeta"])

            materialize("events", "abc")

            self.assertCountEqual(
                get_materialized_columns("events", use_cache=True).keys(),
                ["$foo", "$bar", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS],
            )

        with freeze_time("2020-01-04T14:00:01Z"):
            self.assertCountEqual(
                get_materialized_columns("events", use_cache=True).keys(),
                ["$foo", "$bar", "abc", *EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS],
            )

    def test_materialized_column_naming(self):
        random.seed(0)

        materialize("events", "$foO();--sqlinject")
        materialize("events", "$foO();ääsqlinject")
        materialize("events", "$foO_____sqlinject")
        materialize("person", "SoMePrOp")

        self.assertDictContainsSubset(
            {
                "$foO();--sqlinject": "mat_$foO_____sqlinject",
                "$foO();ääsqlinject": "mat_$foO_____sqlinject_yWAc",
                "$foO_____sqlinject": "mat_$foO_____sqlinject_qGFz",
            },
            get_materialized_columns("events"),
        )

        self.assertEqual(get_materialized_columns("person"), {"SoMePrOp": "pmat_SoMePrOp"})

    def test_backfilling_data(self):
        sync_execute("ALTER TABLE events DROP COLUMN IF EXISTS mat_prop")
        sync_execute("ALTER TABLE events DROP COLUMN IF EXISTS mat_another")

        _create_event(
            event="some_event", distinct_id="1", team=self.team, timestamp="2020-01-01 00:00:00", properties={"prop": 1}
        )
        _create_event(
            event="some_event",
            distinct_id="1",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"prop": 2, "another": 5},
        )
        _create_event(
            event="some_event", distinct_id="1", team=self.team, timestamp="2021-05-03 00:00:00", properties={"prop": 3}
        )
        _create_event(event="another_event", distinct_id="1", team=self.team, timestamp="2021-05-04 00:00:00")
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

        materialize("events", "prop")
        materialize("events", "another")

        self.assertEqual(self._count_materialized_rows("mat_prop"), 0)
        self.assertEqual(self._count_materialized_rows("mat_another"), 0)

        with freeze_time("2021-05-10T14:00:01Z"):
            backfill_materialized_columns(
                "events", ["prop", "another"], timedelta(days=50), test_settings={"mutations_sync": "0"}
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
            [("1", ""), ("2", "5"), ("3", ""), ("", ""), ("4", ""), ("", "6"), ("", "7")],
        )

    def test_column_types(self):
        materialize("events", "myprop")

        expr = "replaceRegexpAll(JSONExtractRaw(properties, 'myprop'), '^\"|\"$', '')"
        self.assertEqual(("MATERIALIZED", expr), self._get_column_types("mat_myprop"))

        backfill_materialized_columns("events", ["myprop"], timedelta(days=50))
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
            {"database": CLICKHOUSE_DATABASE, "table": EVENTS_DATA_TABLE(), "column": column},
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
            {"database": CLICKHOUSE_DATABASE, "table": EVENTS_DATA_TABLE(), "column": column},
        )[0]
