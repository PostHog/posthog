from datetime import datetime, timedelta
from pprint import pprint
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrendsNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d 00:00:00"


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrendsNew(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_no_event_in_period(self):
        _create_person(distinct_ids=["user a"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-06 21:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTrendsNew(filter, self.team)
        results = funnel_trends.perform_query()

        self.assertEqual(len(results), 7)

    def test_only_one_user_reached_one_step(self):
        _create_person(distinct_ids=["user a"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-07 19:00:00")
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTrendsNew(filter, self.team)
        results = funnel_trends.perform_query()
        self.assertEqual(len(results), 7)

        day_1, day_2, day_3, day_4, day_5, day_6, day_7 = results

        self.assertEqual(day_1["started_count"], 1)
        self.assertEqual(day_1["ended_count"], 0)
        self.assertEqual(day_1["percent_ended"], 0)
        self.assertEqual(len(day_1["person_ids_started"]), 1)  # ignoring values since they are random UUIDs
        self.assertEqual(len(day_1["person_ids_ended"]), 0)
        self.assertEqual(day_1["timestamp"], datetime(2021, 6, 7, 0, 0))
        self.assertEqual(day_1["is_period_final"], True)

        self.assertDictEqual(
            day_2,
            {
                "ended_count": 0,
                "is_period_final": True,
                "percent_ended": 0.0,
                "person_ids_ended": [],
                "person_ids_started": [],
                "started_count": 0,
                "timestamp": datetime(2021, 6, 8, 0, 0),
            },
        )
        self.assertDictEqual(
            day_3,
            {
                "ended_count": 0,
                "is_period_final": True,
                "percent_ended": 0.0,
                "person_ids_ended": [],
                "person_ids_started": [],
                "started_count": 0,
                "timestamp": datetime(2021, 6, 9, 0, 0),
            },
        )
        self.assertDictEqual(
            day_4,
            {
                "ended_count": 0,
                "is_period_final": True,
                "percent_ended": 0.0,
                "person_ids_ended": [],
                "person_ids_started": [],
                "started_count": 0,
                "timestamp": datetime(2021, 6, 10, 0, 0),
            },
        )
        self.assertDictEqual(
            day_5,
            {
                "ended_count": 0,
                "is_period_final": True,
                "percent_ended": 0.0,
                "person_ids_ended": [],
                "person_ids_started": [],
                "started_count": 0,
                "timestamp": datetime(2021, 6, 11, 0, 0),
            },
        )
        self.assertDictEqual(
            day_6,
            {
                "ended_count": 0,
                "is_period_final": True,
                "percent_ended": 0.0,
                "person_ids_ended": [],
                "person_ids_started": [],
                "started_count": 0,
                "timestamp": datetime(2021, 6, 12, 0, 0),
            },
        )
        self.assertDictEqual(
            day_7,
            {
                "ended_count": 0,
                "is_period_final": True,
                "percent_ended": 0.0,
                "person_ids_ended": [],
                "person_ids_started": [],
                "started_count": 0,
                "timestamp": datetime(2021, 6, 13, 0, 0),
            },
        )

    # minute, hour, day, week, month
    def test_hour_interval(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "hour",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrendsNew(filter, self.team).perform_query()
        self.assertEqual(len(results), 145)

    def test_day_interval(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrendsNew(filter, self.team).perform_query()
        self.assertEqual(len(results), 7)

    def test_week_interval(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "week",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrendsNew(filter, self.team).perform_query()
        self.assertEqual(2, len(results))

    def test_month_interval(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "month",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrendsNew(filter, self.team).perform_query()
        self.assertEqual(len(results), 1)
