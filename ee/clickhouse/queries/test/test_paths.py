from typing import Tuple
from unittest.mock import MagicMock
from uuid import uuid4

from django.test import TestCase
from freezegun import freeze_time

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries import ClickhousePaths
from ee.clickhouse.queries.paths import ClickhousePathsPersons
from ee.clickhouse.queries.paths.path_event_query import PathEventQuery
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import (
    FUNNEL_PATH_AFTER_STEP,
    FUNNEL_PATH_BEFORE_STEP,
    FUNNEL_PATH_BETWEEN_STEPS,
    INSIGHT_FUNNELS,
    PAGEVIEW_EVENT,
    SCREEN_EVENT,
)
from posthog.models.filters import Filter, PathFilter
from posthog.models.person import Person
from posthog.queries.test.test_paths import paths_test_factory
from posthog.test.base import test_with_materialized_columns


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


ONE_MINUTE = 60_000  # 1 minute in milliseconds


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, _create_event, Person.objects.create)):  # type: ignore

    maxDiff = None

    def _get_people_at_path(self, filter, path_start=None, path_end=None, funnel_filter=None, path_dropoff=None):
        person_filter = filter.with_data(
            {"path_start_key": path_start, "path_end_key": path_end, "path_dropoff_key": path_dropoff}
        )
        result = ClickhousePathsPersons(person_filter, self.team, funnel_filter)._exec_query()
        return [row[0] for row in result]

    def test_denormalized_properties(self):
        materialize("events", "$current_url")
        materialize("events", "$screen_name")

        query = ClickhousePaths(team=self.team, filter=PathFilter(data={"path_type": PAGEVIEW_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        query = ClickhousePaths(team=self.team, filter=PathFilter(data={"path_type": SCREEN_EVENT})).get_query()
        self.assertNotIn("json", query.lower())

        self.test_current_url_paths_and_logic()

    def test_step_limit(self):

        with freeze_time("2012-01-01T03:21:34.000Z"):
            p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["fake"])
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
            response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response, [{"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE}]
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "1_/1", "2_/2"))
            self.assertEqual([], self._get_people_at_path(filter, "2_/2", "3_/3"))

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 3})
            response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                    {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "2_/2", "3_/3"))

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(data={"step_limit": 4})
            response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                    {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                    {"source": "3_/3", "target": "4_/4", "value": 1, "average_conversion_time": 3 * ONE_MINUTE},
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "1_/1", "2_/2"))
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "2_/2", "3_/3"))
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "3_/3", "4_/4"))

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

        filter = PathFilter(data={"step_limit": 4, "date_from": "2012-01-01", "include_event_types": ["$pageview"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 2, "average_conversion_time": 1.5 * ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 2, "average_conversion_time": 3 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/4", "value": 1, "average_conversion_time": 3 * ONE_MINUTE},
            ],
        )

    # this tests to make sure that paths don't get scrambled when there are several similar variations
    def test_path_event_ordering(self):
        for i in range(50):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:01:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:02:00")

            if i % 2 == 0:
                _create_event(
                    event="step branch", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:03:00"
                )

        filter = PathFilter(
            data={"date_from": "2021-05-01", "date_to": "2021-05-03", "include_event_types": ["custom_event"]}
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {"source": "1_step one", "target": "2_step two", "value": 50, "average_conversion_time": 60000.0},
                {"source": "2_step two", "target": "3_step three", "value": 50, "average_conversion_time": 60000.0},
                {"source": "3_step three", "target": "4_step branch", "value": 25, "average_conversion_time": 60000.0},
            ],
        )

    def _create_sample_data_multiple_dropoffs(self):
        for i in range(5):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="between_step_1_a", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:01:00"
            )
            _create_event(
                event="between_step_1_b", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:02:00"
            )
            _create_event(
                event="between_step_1_c", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:03:00"
            )
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:04:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:05:00")

        for i in range(5, 15):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="between_step_1_a", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:01:00"
            )
            _create_event(
                event="between_step_1_b", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:02:00"
            )
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:03:00")
            _create_event(
                event="between_step_2_a", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:04:20"
            )
            _create_event(
                event="between_step_2_b", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:05:40"
            )

        for i in range(15, 35):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="step dropoff1", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:01:00"
            )
            _create_event(
                event="step dropoff2", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:02:00"
            )
            if i % 2 == 0:
                _create_event(
                    event="step branch", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:03:00"
                )

    def test_path_by_grouping(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "path_groupings": ["between_step_1_*", "between_step_2_*", "step drop*"],
        }
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
                {
                    "source": "2_between_step_1_*",
                    "target": "3_step two",
                    "value": 15,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_step drop*",
                    "target": "3_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "3_step two",
                    "target": "4_between_step_2_*",
                    "value": 10,
                    "average_conversion_time": 160000,
                },
                {"source": "3_step two", "target": "4_step three", "value": 5, "average_conversion_time": ONE_MINUTE,},
            ],
        )

    def test_path_by_grouping_replacement(self):
        Person.objects.create(distinct_ids=[f"user_1"], team=self.team)
        _create_event(
            event="$pageview",
            distinct_id=f"user_1",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$current_url": "test.com/step1"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_1",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
            properties={"$current_url": "test.com/step2"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_1",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
            properties={"$current_url": "test.com/step3?key=value1"},
        )

        Person.objects.create(distinct_ids=[f"user_2"], team=self.team)
        _create_event(
            event="$pageview",
            distinct_id=f"user_2",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$current_url": "test.com/step1"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_2",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
            properties={"$current_url": "test.com/step2"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_2",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
            properties={"$current_url": "test.com/step3?key=value2"},
        )

        Person.objects.create(distinct_ids=[f"user_3"], team=self.team)
        _create_event(
            event="$pageview",
            distinct_id=f"user_3",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$current_url": "test.com/step1"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_3",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
            properties={"$current_url": "test.com/step2"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_3",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
            properties={"$current_url": "test.com/step3?key=value3"},
        )

        data = {
            "insight": INSIGHT_FUNNELS,
            "include_event_types": ["$pageview"],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "path_replacements": [{"?<param>": "\\?(.*)"}],  # noqa: W605
        }
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter).run()

        self.assertEqual(
            response,
            [
                {
                    "source": "1_test.com/step1",
                    "target": "2_test.com/step2",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_test.com/step2",
                    "target": "3_test.com/step3?<param>",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    def test_path_by_grouping_replacement_multiple(self):
        Person.objects.create(distinct_ids=[f"user_1"], team=self.team)
        _create_event(
            event="$pageview",
            distinct_id=f"user_1",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$current_url": "test.com/step1"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_1",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
            properties={"$current_url": "test.com/step2/5"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_1",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
            properties={"$current_url": "test.com/step2/5?key=value1"},
        )

        Person.objects.create(distinct_ids=[f"user_2"], team=self.team)
        _create_event(
            event="$pageview",
            distinct_id=f"user_2",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$current_url": "test.com/step1"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_2",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
            properties={"$current_url": "test.com/step2/5"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_2",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
            properties={"$current_url": "test.com/step2/5?key=value2"},
        )

        Person.objects.create(distinct_ids=[f"user_3"], team=self.team)
        _create_event(
            event="$pageview",
            distinct_id=f"user_3",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$current_url": "test.com/step1"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_3",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
            properties={"$current_url": "test.com/step2/5"},
        )
        _create_event(
            event="$pageview",
            distinct_id=f"user_3",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
            properties={"$current_url": "test.com/step2/5?key=value3"},
        )

        data = {
            "insight": INSIGHT_FUNNELS,
            "include_event_types": ["$pageview"],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "path_replacements": [{"?<param>": "\\?(.*)"}, {"/<id>": "/\\d+(/|\\?)?"}],
        }
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_test.com/step1",
                    "target": "2_test.com/step2/<id>",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_test.com/step2/<id>",
                    "target": "3_test.com/step2/<id><param>",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    def test_path_by_funnel_after_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {"source": "1_step one", "target": "2_step dropoff1", "value": 20, "average_conversion_time": 60000.0},
                {
                    "source": "2_step dropoff1",
                    "target": "3_step dropoff2",
                    "value": 20,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_step dropoff2",
                    "target": "4_step branch",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
            ],
        )
        self.assertEqual(20, len(self._get_people_at_path(path_filter, "1_step one", "2_step dropoff1", funnel_filter)))
        self.assertEqual(
            20, len(self._get_people_at_path(path_filter, "2_step dropoff1", "3_step dropoff2", funnel_filter))
        )
        self.assertEqual(
            10, len(self._get_people_at_path(path_filter, "3_step dropoff2", "4_step branch", funnel_filter))
        )
        self.assertEqual(
            0, len(self._get_people_at_path(path_filter, "4_step branch", "3_step dropoff2", funnel_filter))
        )

    def test_path_by_funnel_after_step_respects_conversion_window(self):
        # note events happen after 1 day
        for i in range(5):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="between_step_1_a", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-02 00:00:00"
            )
            _create_event(
                event="between_step_1_b", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00"
            )
            _create_event(
                event="between_step_1_c", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-04 00:00:00"
            )
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-06 00:00:00")

        for i in range(15, 35):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="step dropoff1", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-02 00:00:00"
            )
            _create_event(
                event="step dropoff2", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00"
            )
            if i % 2 == 0:
                _create_event(
                    event="step branch", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-04 00:00:00"
                )

        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step dropoff1",
                    "value": 20,
                    "average_conversion_time": ONE_MINUTE * 60 * 24,
                },
                {
                    "source": "2_step dropoff1",
                    "target": "3_step dropoff2",
                    "value": 20,
                    "average_conversion_time": ONE_MINUTE * 60 * 24,
                },
                {
                    "source": "3_step dropoff2",
                    "target": "4_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE * 60 * 24,
                },
            ],
        )
        self.assertEqual(20, len(self._get_people_at_path(path_filter, "1_step one", "2_step dropoff1", funnel_filter)))
        self.assertEqual(
            20, len(self._get_people_at_path(path_filter, "2_step dropoff1", "3_step dropoff2", funnel_filter))
        )
        self.assertEqual(
            10, len(self._get_people_at_path(path_filter, "3_step dropoff2", "4_step branch", funnel_filter))
        )
        self.assertEqual(
            0, len(self._get_people_at_path(path_filter, "4_step branch", "3_step dropoff2", funnel_filter))
        )

    def test_path_by_funnel_after_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step two",
                    "target": "2_between_step_2_a",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
                {
                    "source": "2_between_step_2_a",
                    "target": "3_between_step_2_b",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
                {"source": "1_step two", "target": "2_step three", "value": 5, "average_conversion_time": 60000.0},
            ],
        )

    def test_path_by_funnel_after_step_limit(self):
        self._create_sample_data_multiple_dropoffs()

        # add more than 100. Previously, the funnel limit at 100 was stopping all users from showing up
        for i in range(100, 200):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(
                event="between_step_1_a", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:01:00"
            )
            _create_event(
                event="between_step_1_b", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:02:00"
            )
            _create_event(
                event="between_step_1_c", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:03:00"
            )
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:04:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:05:00")

        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {"source": "1_step two", "target": "2_step three", "value": 105, "average_conversion_time": 60000.0},
                {
                    "source": "1_step two",
                    "target": "2_between_step_2_a",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
                {
                    "source": "2_between_step_2_a",
                    "target": "3_between_step_2_b",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
            ],
        )

    def test_path_by_funnel_before_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_BEFORE_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -3,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_a",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_between_step_1_a",
                    "target": "3_between_step_1_b",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_step two",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_step two",
                    "target": "5_between_step_2_a",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
            ],
        )

    def test_path_by_funnel_before_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_BEFORE_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_a",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_between_step_1_a",
                    "target": "3_between_step_1_b",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_step two",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_between_step_1_c",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_between_step_1_c",
                    "target": "5_step two",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    def test_path_by_funnel_between_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_BETWEEN_STEPS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data)
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_a",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_between_step_1_a",
                    "target": "3_between_step_1_b",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_step two",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_between_step_1_c",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_between_step_1_c",
                    "target": "5_step two",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
            ],
        )
        self.assertEqual(
            15, len(self._get_people_at_path(path_filter, "1_step one", "2_between_step_1_a", funnel_filter))
        )
        self.assertEqual(
            15, len(self._get_people_at_path(path_filter, "2_between_step_1_a", "3_between_step_1_b", funnel_filter))
        )
        self.assertEqual(
            10, len(self._get_people_at_path(path_filter, "3_between_step_1_b", "4_step two", funnel_filter))
        )
        self.assertEqual(
            5, len(self._get_people_at_path(path_filter, "3_between_step_1_b", "4_between_step_1_c", funnel_filter))
        )
        self.assertEqual(
            5, len(self._get_people_at_path(path_filter, "4_between_step_1_c", "5_step two", funnel_filter))
        )

    @test_with_materialized_columns(["$current_url"])
    def test_paths_end(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:03:00",
        )
        _create_event(
            properties={"$current_url": "/4"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:04:00",
        )
        _create_event(
            properties={"$current_url": "/5"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:05:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:06:00",
        )
        _create_event(
            properties={"$current_url": "/after"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:07:00",
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_event(
            properties={"$current_url": "/5"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/4"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:03:00",
        )
        _create_event(
            properties={"$current_url": "/after"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:04:00",
        )

        filter = PathFilter(
            data={
                "path_type": "$pageview",
                "end_point": "/about",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter,)
        self.assertEqual(
            response,
            [
                {"source": "1_/2", "target": "2_/3", "value": 1, "average_conversion_time": 60000.0},
                {"source": "1_/3", "target": "2_/4", "value": 1, "average_conversion_time": 60000.0},
                {"source": "1_/5", "target": "2_/about", "value": 1, "average_conversion_time": 60000.0},
                {"source": "2_/3", "target": "3_/4", "value": 1, "average_conversion_time": 60000.0},
                {"source": "2_/4", "target": "3_/about", "value": 1, "average_conversion_time": 60000.0},
                {"source": "3_/4", "target": "4_/5", "value": 1, "average_conversion_time": 60000.0},
                {"source": "4_/5", "target": "5_/about", "value": 1, "average_conversion_time": 60000.0},
            ],
        )

    def test_event_inclusion_exclusion_filters(self):

        # P1 for pageview event
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2/"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P2 for screen event
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"])
        _create_event(
            properties={"$screen_name": "/screen1"},
            distinct_id="p2",
            event="$screen",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$screen_name": "/screen2"},
            distinct_id="p2",
            event="$screen",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$screen_name": "/screen3"},
            distinct_id="p2",
            event="$screen",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P3 for custom event
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"])
        _create_event(
            distinct_id="p3", event="/custom1", team=self.team, timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            distinct_id="p3", event="/custom2", team=self.team, timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            distinct_id="p3", event="/custom3", team=self.team, timestamp="2012-01-01T03:24:34.000Z",
        )

        filter = PathFilter(data={"step_limit": 4, "date_from": "2012-01-01", "include_event_types": ["$pageview"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data({"include_event_types": ["$screen"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/screen1", "target": "2_/screen2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/screen2", "target": "3_/screen3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data({"include_event_types": ["custom_event"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/custom1", "target": "2_/custom2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/custom2", "target": "3_/custom3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data({"include_event_types": [], "include_custom_events": ["/custom1", "/custom2"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [{"source": "1_/custom1", "target": "2_/custom2", "value": 1, "average_conversion_time": ONE_MINUTE},],
        )

        filter = filter.with_data({"include_event_types": [], "include_custom_events": ["/custom3", "blah"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response, [],
        )

        filter = filter.with_data(
            {"include_event_types": ["$pageview", "$screen", "custom_event"], "include_custom_events": []}
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "1_/custom1", "target": "2_/custom2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "1_/screen1", "target": "2_/screen2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "2_/custom2", "target": "3_/custom3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "2_/screen2", "target": "3_/screen3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data(
            {
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "include_custom_events": [],
                "exclude_events": ["/custom1", "/1", "/2", "/3"],
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {"source": "1_/custom2", "target": "2_/custom3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "1_/screen1", "target": "2_/screen2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/screen2", "target": "3_/screen3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

    def test_event_exclusion_filters_with_wildcards(self):

        # P1 for pageview event /2/bar/1/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2/bar/1/foo"},  # regex matches, despite beginning with `/2/`
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P2 for pageview event /bar/2/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/bar/2/foo"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P3 for pageview event /bar/3/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p3",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/bar/33/foo"},
            distinct_id="p3",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p3",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        filter = PathFilter(
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "exclude_events": ["/bar/*/foo"],
                "include_event_types": ["$pageview"],
                "path_groupings": ["/bar/*/foo"],
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response, [{"source": "1_/1", "target": "2_/3", "value": 3, "average_conversion_time": 3 * ONE_MINUTE},],
        )

        filter = filter.with_data({"path_groupings": ["/xxx/invalid/*"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(len(response), 6)

    def test_event_inclusion_exclusion_filters_across_single_person(self):

        # P1 for pageview event, screen event, and custom event all together
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )
        _create_event(
            properties={"$screen_name": "/screen1"},
            distinct_id="p1",
            event="$screen",
            team=self.team,
            timestamp="2012-01-01T03:25:34.000Z",
        )
        _create_event(
            properties={"$screen_name": "/screen2"},
            distinct_id="p1",
            event="$screen",
            team=self.team,
            timestamp="2012-01-01T03:26:34.000Z",
        )
        _create_event(
            properties={"$screen_name": "/screen3"},
            distinct_id="p1",
            event="$screen",
            team=self.team,
            timestamp="2012-01-01T03:28:34.000Z",
        )
        _create_event(
            distinct_id="p1", event="/custom1", team=self.team, timestamp="2012-01-01T03:29:34.000Z",
        )
        _create_event(
            distinct_id="p1", event="/custom2", team=self.team, timestamp="2012-01-01T03:30:34.000Z",
        )
        _create_event(
            distinct_id="p1", event="/custom3", team=self.team, timestamp="2012-01-01T03:32:34.000Z",
        )

        filter = PathFilter(data={"step_limit": 10, "date_from": "2012-01-01"})  # include everything, exclude nothing
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/screen1", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "4_/screen1", "target": "5_/screen2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "5_/screen2", "target": "6_/screen3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "6_/screen3", "target": "7_/custom1", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "7_/custom1", "target": "8_/custom2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "8_/custom2", "target": "9_/custom3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data({"include_event_types": ["$pageview", "$screen"]})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/screen1", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "4_/screen1", "target": "5_/screen2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "5_/screen2", "target": "6_/screen3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data(
            {"include_event_types": ["$pageview", "$screen"], "include_custom_events": ["/custom2"]}
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/screen1", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "4_/screen1", "target": "5_/screen2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "5_/screen2", "target": "6_/screen3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "6_/screen3", "target": "7_/custom2", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

        filter = filter.with_data(
            {
                "include_event_types": ["$pageview", "custom_event"],
                "include_custom_events": [],
                "exclude_events": ["/custom1", "/custom3"],
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
                {"source": "3_/3", "target": "4_/custom2", "value": 1, "average_conversion_time": 6 * ONE_MINUTE},
            ],
        )

    def test_path_respect_session_limits(self):
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
            properties={"$current_url": "/1"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-02T03:21:54.000Z",  # new day, new session
        )
        _create_event(
            properties={"$current_url": "/2/"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-02T03:22:54.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-02T03:26:54.000Z",
        )

        filter = PathFilter(data={"date_from": "2012-01-01"})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 2, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 2, "average_conversion_time": 3 * ONE_MINUTE},
            ],
        )

    def test_path_removes_duplicates(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["fake"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:54.000Z",
        )
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2/"},  # trailing slash should be removed
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:54.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="fake",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:54.000Z",
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
            properties={"$current_url": "/2/"},
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

        filter = PathFilter(data={"date_from": "2012-01-01"})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/2", "value": 2, "average_conversion_time": 1.5 * ONE_MINUTE},
                {"source": "2_/2", "target": "3_/3", "value": 2, "average_conversion_time": 3 * ONE_MINUTE},
            ],
        )

    @test_with_materialized_columns(["$current_url"])
    def test_paths_start_and_end(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:03:00",
        )
        _create_event(
            properties={"$current_url": "/4"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:04:00",
        )
        _create_event(
            properties={"$current_url": "/5"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:05:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:06:00",
        )
        _create_event(
            properties={"$current_url": "/after"},
            distinct_id="person_1",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:07:00",
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_event(
            properties={"$current_url": "/5"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )

        p3 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/4"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:03:00",
        )
        _create_event(
            properties={"$current_url": "/after"},
            distinct_id="person_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:04:00",
        )

        filter = PathFilter(
            data={
                "path_type": "$pageview",
                "start_point": "/5",
                "end_point": "/about",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter,)
        self.assertEqual(
            response, [{"source": "1_/5", "target": "2_/about", "value": 2, "average_conversion_time": 60000.0}]
        )
        self.assertCountEqual(self._get_people_at_path(filter, "1_/5", "2_/about"), [p1.uuid, p2.uuid])

        # test aggregation for long paths
        filter = filter.with_data({"start_point": "/2", "step_limit": 4})
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter,)
        self.assertEqual(
            response,
            [
                {"source": "1_/2", "target": "2_/3", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/3", "target": "3_...", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "3_...", "target": "4_/5", "value": 1, "average_conversion_time": ONE_MINUTE},
                {"source": "4_/5", "target": "5_/about", "value": 1, "average_conversion_time": ONE_MINUTE},
            ],
        )
        self.assertCountEqual(self._get_people_at_path(filter, "3_...", "4_/5"), [p1.uuid])

    def test_properties_queried_using_path_filter(self):
        def should_query_list(filter) -> Tuple[bool, bool]:
            path_query = PathEventQuery(filter, self.team.id)
            return (path_query._should_query_url(), path_query._should_query_screen())

        filter = PathFilter()
        self.assertEqual(should_query_list(filter), (True, True))

        filter = PathFilter({"include_event_types": ["$pageview"]})
        self.assertEqual(should_query_list(filter), (True, False))

        filter = PathFilter({"include_event_types": ["$screen"]})
        self.assertEqual(should_query_list(filter), (False, True))

        filter = filter.with_data({"include_event_types": [], "include_custom_events": ["/custom1", "/custom2"]})
        self.assertEqual(should_query_list(filter), (False, False))

        filter = filter.with_data(
            {"include_event_types": ["$pageview", "$screen", "custom_event"], "include_custom_events": []}
        )
        self.assertEqual(should_query_list(filter), (True, True))

        filter = filter.with_data(
            {
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "include_custom_events": [],
                "exclude_events": ["/custom1"],
            }
        )
        self.assertEqual(should_query_list(filter), (True, True))

        filter = filter.with_data(
            {"include_event_types": [], "include_custom_events": [], "exclude_events": ["$pageview"],}
        )
        self.assertEqual(should_query_list(filter), (False, True))

    def test_path_grouping_across_people(self):

        # P1 for pageview event /2/bar/1/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2/bar/1/foo"},  # regex matches, despite beginning with `/2/`
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P2 for pageview event /bar/2/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/bar/2/foo"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P3 for pageview event /bar/3/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p3",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/bar/33/foo"},
            distinct_id="p3",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p3",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        filter = PathFilter(
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "include_event_types": ["$pageview"],
                "path_groupings": ["/bar/*/foo"],
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/bar/*/foo", "value": 3, "average_conversion_time": ONE_MINUTE},
                {"source": "2_/bar/*/foo", "target": "3_/3", "value": 3, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

    def test_path_grouping_with_evil_input(self):

        evil_string = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!"
        # P1 for pageview event /2/bar/1/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"])
        _create_event(
            properties={"$current_url": evil_string},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2/bar/aaa"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3"},
            distinct_id="p1",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        # P2 for pageview event /2/bar/2/foo
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"])
        _create_event(
            properties={"$current_url": "/1"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:21:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/2/3?q=1"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:22:34.000Z",
        )
        _create_event(
            properties={"$current_url": "/3?q=1"},
            distinct_id="p2",
            event="$pageview",
            team=self.team,
            timestamp="2012-01-01T03:24:34.000Z",
        )

        filter = PathFilter(
            data={
                "date_from": "2012-01-01",
                "include_event_types": ["$pageview"],
                "path_groupings": ["(a+)+", "[aaa|aaaa]+", "1.*", ".*", "/3?q=1", "/3*"],
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {"source": "1_/1", "target": "2_/3*", "value": 1, "average_conversion_time": 3 * ONE_MINUTE},
                {
                    "source": f"1_{evil_string}",
                    "target": "2_/2/bar/aaa",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {"source": "2_/2/bar/aaa", "target": "3_/3*", "value": 1, "average_conversion_time": 2 * ONE_MINUTE},
            ],
        )

    def test_paths_person_dropoffs(self):

        # 5 people do 2 events
        for i in range(5):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:04:00")

        # 10 people do 3 events
        for i in range(5, 15):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:04:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:05:00")

        # 20 people do 4 events
        for i in range(15, 35):
            Person.objects.create(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:04:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:05:00")
            _create_event(event="step four", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:06:00")

        filter = PathFilter(
            data={
                "include_event_types": ["custom_event"],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            }
        )
        self.assertEqual(5, len(self._get_people_at_path(filter, path_dropoff="2_step two")))  # 5 dropoff at step 2
        self.assertEqual(35, len(self._get_people_at_path(filter, path_end="2_step two")))  # 35 total reach step 2
        self.assertEqual(
            30, len(self._get_people_at_path(filter, path_start="2_step two"))
        )  # 30 total reach after step 2

        self.assertEqual(10, len(self._get_people_at_path(filter, path_dropoff="3_step three")))  # 10 dropoff at step 3
        self.assertEqual(30, len(self._get_people_at_path(filter, path_end="3_step three")))  # 30 total reach step 3
        self.assertEqual(
            20, len(self._get_people_at_path(filter, path_start="3_step three"))
        )  # 20 total reach after step 3

        self.assertEqual(20, len(self._get_people_at_path(filter, path_dropoff="4_step four")))  # 20 dropoff at step 4
        self.assertEqual(20, len(self._get_people_at_path(filter, path_end="4_step four")))  # 20 total reach step 4
        self.assertEqual(
            0, len(self._get_people_at_path(filter, path_start="4_step four"))
        )  # 0 total reach after step 4

    def test_paths_start_dropping_orphaned_edges(self):

        for i in range(5):
            # 5 people going through this route to increase weights
            Person.objects.create(team_id=self.team.pk, distinct_ids=[f"person_{i}"])
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            )
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            )
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            )
            _create_event(
                properties={"$current_url": "/4"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:04:00",
            )
            _create_event(
                properties={"$current_url": "/5"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:05:00",
            )
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:06:00",
            )
            _create_event(
                properties={"$current_url": "/after"},
                distinct_id=f"person_{i}",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:07:00",
            )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_r_2"])
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="person_r_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/a"},
            distinct_id="person_r_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:30",
        )
        _create_event(
            properties={"$current_url": "/x"},
            distinct_id="person_r_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_r_2",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:03:00",
        )

        p3 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_r_3"])
        _create_event(
            properties={"$current_url": "/2"},
            distinct_id="person_r_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:00",
        )
        _create_event(
            properties={"$current_url": "/b"},
            distinct_id="person_r_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:01:30",
        )
        _create_event(
            properties={"$current_url": "/x"},
            distinct_id="person_r_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:02:00",
        )
        _create_event(
            properties={"$current_url": "/about"},
            distinct_id="person_r_3",
            event="$pageview",
            team=self.team,
            timestamp="2021-05-01 00:03:00",
        )

        # /x -> /about has higher weight than /2 -> /a -> /x and /2 -> /b -> /x

        filter = PathFilter(
            data={
                "path_type": "$pageview",
                "start_point": "/2",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "edge_limit": "6",
            }
        )
        response = ClickhousePaths(team=self.team, filter=filter).run(team=self.team, filter=filter,)
        self.assertEqual(
            response,
            [
                {"source": "1_/2", "target": "2_/3", "value": 5, "average_conversion_time": 60000.0},
                {"source": "2_/3", "target": "3_/4", "value": 5, "average_conversion_time": 60000.0},
                {"source": "3_/4", "target": "4_/5", "value": 5, "average_conversion_time": 60000.0},
                {"source": "4_/5", "target": "5_/about", "value": 5, "average_conversion_time": 60000.0},
                # {'source': '3_/x', 'target': '4_/about', 'value': 2, 'average_conversion_time': 60000.0}, # gets deleted by validation since dangling
                {"source": "1_/2", "target": "2_/a", "value": 1, "average_conversion_time": 30000.0},
            ],
        )

    def test_path_min_edge_weight(self):
        # original data from test_path_by_grouping.py
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "min_edge_weight": 15,
            "path_groupings": ["between_step_1_*", "between_step_2_*", "step drop*"],
        }
        path_filter = PathFilter(data=data)
        response = ClickhousePaths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
                {
                    "source": "2_between_step_1_*",
                    "target": "3_step two",
                    "value": 15,
                    "average_conversion_time": ONE_MINUTE,
                },
            ],
        )

        path_filter = path_filter.with_data({"edge_limit": 2})
        response = ClickhousePaths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
            ],
        )

        path_filter = path_filter.with_data({"edge_limit": 20, "max_edge_weight": 11, "min_edge_weight": 6})
        response = ClickhousePaths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "2_step drop*",
                    "target": "3_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "3_step two",
                    "target": "4_between_step_2_*",
                    "value": 10,
                    "average_conversion_time": 160000,
                },
            ],
        )


class TestClickhousePathsEdgeValidation(TestCase):

    BASIC_PATH = [("1_a", "2_b"), ("2_b", "3_c"), ("3_c", "4_d")]  # a->b->c->d
    BASIC_PATH_2 = [("1_x", "2_y"), ("2_y", "3_z")]  # x->y->z

    def test_basic_forest(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2

        results = ClickhousePaths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2)

    def test_basic_forest_with_dangling_edges(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d"), ("2_xxx", "3_yyy")]

        results = ClickhousePaths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2)

    def test_basic_forest_with_dangling_and_cross_edges(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d"), ("2_y", "3_c")]

        results = ClickhousePaths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2 + [("2_y", "3_c")])

    def test_no_start_point(self):
        edges = set(self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d")])
        edges.remove(("1_a", "2_b"))  # remove first start point
        edges = list(edges)  # type: ignore

        results = ClickhousePaths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH_2)
