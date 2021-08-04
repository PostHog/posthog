from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import get_materialized_columns, materialize
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import BaseTest


class TestMaterializedColumns(ClickhouseTestMixin, BaseTest):
    def tearDown(self):
        super().tearDown()
        # :TRICKY: Reset the fetch method cache after tests
        get_materialized_columns.__cache = {}

    def test_get_columns_default(self):
        self.assertCountEqual(get_materialized_columns("events"), [])
        self.assertCountEqual(get_materialized_columns("person"), [])

    def test_caching_and_materializing(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            materialize("events", "$foo")
            materialize("events", "$bar")
            materialize("person", "$zeta")

            self.assertCountEqual(get_materialized_columns("events"), ["$foo", "$bar"])
            self.assertCountEqual(get_materialized_columns("person"), ["$zeta"])

            materialize("events", "abc")

            self.assertCountEqual(get_materialized_columns("events"), ["$foo", "$bar"])

        with freeze_time("2020-01-04T14:00:01Z"):
            self.assertCountEqual(get_materialized_columns("events"), ["$foo", "$bar", "abc"])
