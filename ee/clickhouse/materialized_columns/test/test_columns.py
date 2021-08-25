import random

from freezegun import freeze_time

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize
from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL
from ee.clickhouse.sql.person import DROP_PERSON_TABLE_SQL, PERSONS_TABLE_SQL
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import BaseTest


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
