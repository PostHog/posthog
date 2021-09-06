import random
from datetime import timedelta
from time import sleep
from unittest.mock import patch
from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import (
    backfill_materialized_columns,
    get_materialized_columns,
    materialize,
)
from ee.clickhouse.models.event import create_event
from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
from ee.clickhouse.sql.person import DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return pk


class TestMaterializedColumns(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(EVENTS_TABLE_SQL)
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(PERSONS_TABLE_SQL)

    def tearDown(self):
        super().tearDown()
        sync_execute(DROP_EVENTS_TABLE_SQL)
        sync_execute(EVENTS_TABLE_SQL)
        sync_execute(DROP_PERSON_TABLE_SQL)
        sync_execute(PERSONS_TABLE_SQL)

    def test_get_columns_default(self):
        self.assertCountEqual(get_materialized_columns("events"), [])
        self.assertCountEqual(get_materialized_columns("person"), [])

    def test_caching_and_materializing(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            materialize("events", "$foo")
            materialize("events", "$bar")
            materialize("person", "$zeta")

            self.assertCountEqual(get_materialized_columns("events", use_cache=True).keys(), ["$foo", "$bar"])
            self.assertCountEqual(get_materialized_columns("person", use_cache=True).keys(), ["$zeta"])

            materialize("events", "abc")

            self.assertCountEqual(get_materialized_columns("events", use_cache=True).keys(), ["$foo", "$bar"])

        with freeze_time("2020-01-04T14:00:01Z"):
            self.assertCountEqual(get_materialized_columns("events", use_cache=True).keys(), ["$foo", "$bar", "abc"])

    def test_materialized_column_naming(self):
        random.seed(0)

        materialize("events", "$foO();--sqlinject")
        materialize("events", "$foO();ääsqlinject")
        materialize("events", "$foO_____sqlinject")
        materialize("person", "SoMePrOp")

        self.assertEqual(
            get_materialized_columns("events"),
            {
                "$foO();--sqlinject": "mat_$foO_____sqlinject",
                "$foO();ääsqlinject": "mat_$foO_____sqlinject_yWAc",
                "$foO_____sqlinject": "mat_$foO_____sqlinject_qGFz",
            },
        )

        self.assertEqual(get_materialized_columns("person"), {"SoMePrOp": "pmat_SoMePrOp"})

    @patch("ee.tasks.materialized_column_backfill.check_backfill_done")
    def test_backfilling_data(self, _):
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

    def _count_materialized_rows(self, column):
        return sync_execute(
            """
            SELECT sum(rows)
            FROM system.parts_columns
            WHERE table = 'events'
              AND database = %(database)s
              AND column = %(column)s
        """,
            {"database": CLICKHOUSE_DATABASE, "column": column},
        )[0][0]

    def _get_count_of_mutations_running(self) -> int:
        return sync_execute(
            """
            SELECT count(*)
            FROM system.mutations
            WHERE is_done = 0
        """
        )[0][0]
