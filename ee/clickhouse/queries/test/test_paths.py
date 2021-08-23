from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.queries.paths.paths import ClickhousePathsNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models.filters.path_filter import PathFilter
from posthog.models.person import Person
from posthog.queries.test.test_paths import paths_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


ONE_MINUTE = 60_000  # 1 minute in milliseconds


class TestClickhousePathsOld(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, _create_event, Person.objects.create)):  # type: ignore
    # remove when migrated to new Paths query
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePathsNew, _create_event, Person.objects.create)):  # type: ignore
    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        query, _ = ClickhousePathsNew(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT})).get_query()
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
        with freeze_time("2012-01-01T03:24:34.000Z"):
            _create_event(
                properties={"$current_url": "/3"}, distinct_id="fake", event="$pageview", team=self.team,
            )
        with freeze_time("2012-01-01T03:27:34.000Z"):
            _create_event(
                properties={"$current_url": "/4"}, distinct_id="fake", event="$pageview", team=self.team,
            )

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 2})
            response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response, [{"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE}]
        )

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 3})
            response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 4})
            response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/4", "value": 1, "average_conversion_time": 3 * ONE_MINUTE},
            ],
        )

    def test_step_conversion_times(self):

        Person.objects.create(team_id=self.team.pk, distinct_ids=["fake"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/4"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:27:34.000Z",
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["fake2"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="fake2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="fake2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:23:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="fake2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:27:34.000Z",
        )

        # with freeze_time("2012-01-7T03:21:34.000Z"):
        filter = PathFilter(data={"step_limit": 4, "date_from": "2012-01-01"})
        response = ClickhousePathsNew(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 2, "average_conversion_time": 1.5 * ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 2, "average_conversion_time": 3 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/4", "value": 1, "average_conversion_time": 3 * ONE_MINUTE},
            ],
        )
