from uuid import uuid4

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models.filters.path_filter import PathFilter
from posthog.models.person import Person
from posthog.queries.test.test_paths import paths_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, _create_event, Person.objects.create)):  # type: ignore
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query, _ = ClickhousePaths().get_query(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT}))
        self.assertNotIn("json", query.lower())

        query, _ = ClickhousePaths().get_query(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT}))
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()
