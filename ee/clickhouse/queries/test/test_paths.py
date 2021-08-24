from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.queries.paths.paths import ClickhousePathsNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models.filters import Filter, PathFilter
from posthog.models.person import Person
from posthog.queries.test.test_paths import paths_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhousePathsOld(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, _create_event, Person.objects.create)):  # type: ignore
    # remove when migrated to new Paths query
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        filter = PathFilter(data={"path_type": PAGEVIEW_EVENT})
        query, _ = ClickhousePaths(team=self.team, filter=filter).get_query(team=self.team, filter=filter)
        self.assertNotIn("json", query.lower())

        query, _ = ClickhousePaths(team=self.team, filter=filter).get_query(team=self.team, filter=filter)
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePathsNew, _create_event, Person.objects.create)):  # type: ignore
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        query = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()

    def test_step_limit(self):
        with freeze_time("2012-01-01T03:21:34.000Z"):
            Person.objects.create(team_id=self.team.pk, distinct_ids=["fake"])
            _create_event(
                properties={"$current_url": "/1"}, distinct_id="fake", event="$pageview", team=self.team,
            )
        with freeze_time("2012-01-01T03:22:34.000Z"):
            _create_event(
                properties={"$current_url": "/2"}, distinct_id="fake", event="$pageview", team=self.team,
            )
        with freeze_time("2012-01-01T03:23:34.000Z"):
            _create_event(
                properties={"$current_url": "/3"}, distinct_id="fake", event="$pageview", team=self.team,
            )
        with freeze_time("2012-01-01T03:24:34.000Z"):
            _create_event(
                properties={"$current_url": "/4"}, distinct_id="fake", event="$pageview", team=self.team,
            )

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 2})
            response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(response, [{"source": "1_/1", "target": "2_/2", "value": 1}])

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 3})
            response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [{"source": "1_/1", "target": "2_/2", "value": 1}, {"source": "2_/2", "target": "3_/3", "value": 1}],
        )

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 4})
            response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1},
                {"source": "2_/2", "target": "3_/3", "value": 1},
                {"source": "3_/3", "target": "4_/4", "value": 1},
            ],
        )

    def _create_sample_data_multiple_dropoffs(self):
        for i in range(5):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")

        for i in range(5, 15):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")

        for i in range(15, 35):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="step dropoff1", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:01:00"
            )
            _create_event(
                event="step dropoff2", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:02:00"
            )

    def test_path_by_funnel(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": True,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePathsNew(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {"source": "1_step one", "target": "2_step dropoff1", "value": 20},
                {"source": "2_step dropoff1", "target": "3_step dropoff2", "value": 20},
            ],
        )
