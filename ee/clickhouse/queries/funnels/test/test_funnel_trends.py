from datetime import datetime, timedelta
from uuid import uuid4

import pytz

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d %H:%M:%S"
FORMAT_TIME_DAY_END = "%Y-%m-%d 23:59:59"


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrends(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_sample_data(self):
        # five people, three steps
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_person(distinct_ids=["user_three"], team=self.team)
        _create_person(distinct_ids=["user_four"], team=self.team)
        _create_person(distinct_ids=["user_five"], team=self.team)
        _create_person(distinct_ids=["user_six"], team=self.team)
        _create_person(distinct_ids=["user_seven"], team=self.team)
        _create_person(distinct_ids=["user_eight"], team=self.team)

        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")

        # user_three, funnel steps: one
        _create_event(event="step one", distinct_id="user_three", team=self.team, timestamp="2021-05-06 00:00:00")

        # user_four, funnel steps: none
        _create_event(event="step none", distinct_id="user_four", team=self.team, timestamp="2021-05-06 00:00:00")

        # user_five, funnel steps: one, two, three in the same day
        _create_event(event="step one", distinct_id="user_five", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_five", team=self.team, timestamp="2021-05-01 02:00:00")
        _create_event(event="step three", distinct_id="user_five", team=self.team, timestamp="2021-05-01 03:00:00")

        # user_six, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_six", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_six", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_six", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_seven, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_seven", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_seven", team=self.team, timestamp="2021-05-04 00:00:00")

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

        funnel_trends = ClickhouseFunnelTrends(filter, self.team)
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

        funnel_trends = ClickhouseFunnelTrends(filter, self.team)
        results = funnel_trends.perform_query()
        self.assertEqual(len(results), 7)

        day_1, day_2, day_3, day_4, day_5, day_6, day_7 = results

        self.assertEqual(day_1["entered_count"], 1)
        self.assertEqual(day_1["completed_count"], 0)
        self.assertEqual(day_1["conversion_rate"], 0)
        self.assertEqual(day_1["timestamp"], datetime(2021, 6, 7, 0, 0))
        self.assertEqual(day_1["is_period_final"], True)

        self.assertDictEqual(
            day_2,
            {
                "completed_count": 0,
                "is_period_final": True,
                "conversion_rate": 0,
                "entered_count": 0,
                "timestamp": datetime(2021, 6, 8, 0, 0),
            },
        )
        self.assertDictEqual(
            day_3,
            {
                "completed_count": 0,
                "is_period_final": True,
                "conversion_rate": 0,
                "entered_count": 0,
                "timestamp": datetime(2021, 6, 9, 0, 0),
            },
        )
        self.assertDictEqual(
            day_4,
            {
                "completed_count": 0,
                "is_period_final": True,
                "conversion_rate": 0,
                "entered_count": 0,
                "timestamp": datetime(2021, 6, 10, 0, 0),
            },
        )
        self.assertDictEqual(
            day_5,
            {
                "completed_count": 0,
                "is_period_final": True,
                "conversion_rate": 0,
                "entered_count": 0,
                "timestamp": datetime(2021, 6, 11, 0, 0),
            },
        )
        self.assertDictEqual(
            day_6,
            {
                "completed_count": 0,
                "is_period_final": True,
                "conversion_rate": 0,
                "entered_count": 0,
                "timestamp": datetime(2021, 6, 12, 0, 0),
            },
        )
        self.assertDictEqual(
            day_7,
            {
                "completed_count": 0,
                "is_period_final": True,
                "conversion_rate": 0,
                "entered_count": 0,
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
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()
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
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()
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
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()
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
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()
        self.assertEqual(len(results), 1)

    def test_all_results_for_day_interval(self):
        self._create_sample_data()

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
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()

        saturday = results[0]  # 5/1
        self.assertEqual(3, saturday["completed_count"])
        self.assertEqual(3, saturday["entered_count"])
        self.assertEqual(100, saturday["conversion_rate"])
        self.assertEqual(True, saturday["is_period_final"])

        sunday = results[1]  # 5/2
        self.assertEqual(0, sunday["completed_count"])
        self.assertEqual(2, sunday["entered_count"])
        self.assertEqual(0, sunday["conversion_rate"])
        self.assertEqual(True, sunday["is_period_final"])

        monday = results[2]  # 5/3
        self.assertEqual(0, monday["completed_count"])
        self.assertEqual(0, monday["entered_count"])
        self.assertEqual(0, monday["conversion_rate"])
        self.assertEqual(True, monday["is_period_final"])

        tuesday = results[3]  # 5/4
        self.assertEqual(0, tuesday["completed_count"])
        self.assertEqual(0, tuesday["entered_count"])
        self.assertEqual(0, tuesday["conversion_rate"])
        self.assertEqual(True, tuesday["is_period_final"])

        wednesday = results[4]  # 5/5
        self.assertEqual(0, wednesday["completed_count"])
        self.assertEqual(0, wednesday["entered_count"])
        self.assertEqual(0, wednesday["conversion_rate"])
        self.assertEqual(True, wednesday["is_period_final"])

        thursday = results[5]  # 5/6
        self.assertEqual(0, thursday["completed_count"])
        self.assertEqual(1, thursday["entered_count"])
        self.assertEqual(0, thursday["conversion_rate"])
        self.assertEqual(True, thursday["is_period_final"])

        friday = results[6]  # 5/7
        self.assertEqual(0, friday["completed_count"])
        self.assertEqual(0, friday["entered_count"])
        self.assertEqual(0, friday["conversion_rate"])
        self.assertEqual(True, friday["is_period_final"])

    def test_window_size_one_day(self):
        self._create_sample_data()

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()

        saturday = results[0]  # 5/1
        self.assertEqual(1, saturday["completed_count"])
        self.assertEqual(3, saturday["entered_count"])
        self.assertEqual(33.33, saturday["conversion_rate"])
        self.assertEqual(True, saturday["is_period_final"])

        sunday = results[1]  # 5/2
        self.assertEqual(0, sunday["completed_count"])
        self.assertEqual(2, sunday["entered_count"])
        self.assertEqual(0, sunday["conversion_rate"])
        self.assertEqual(True, sunday["is_period_final"])

        monday = results[2]  # 5/3
        self.assertEqual(0, monday["completed_count"])
        self.assertEqual(0, monday["entered_count"])
        self.assertEqual(0, monday["conversion_rate"])
        self.assertEqual(True, monday["is_period_final"])

        tuesday = results[3]  # 5/4
        self.assertEqual(0, tuesday["completed_count"])
        self.assertEqual(0, tuesday["entered_count"])
        self.assertEqual(0, tuesday["conversion_rate"])
        self.assertEqual(True, tuesday["is_period_final"])

        wednesday = results[4]  # 5/5
        self.assertEqual(0, wednesday["completed_count"])
        self.assertEqual(0, wednesday["entered_count"])
        self.assertEqual(0, wednesday["conversion_rate"])
        self.assertEqual(True, wednesday["is_period_final"])

        thursday = results[5]  # 5/6
        self.assertEqual(0, thursday["completed_count"])
        self.assertEqual(1, thursday["entered_count"])
        self.assertEqual(0, thursday["conversion_rate"])
        self.assertEqual(True, thursday["is_period_final"])

        friday = results[6]  # 5/7
        self.assertEqual(0, friday["completed_count"])
        self.assertEqual(0, friday["entered_count"])
        self.assertEqual(0, friday["conversion_rate"])
        self.assertEqual(True, friday["is_period_final"])

    def test_period_not_final(self):
        now = datetime.now()

        _create_person(distinct_ids=["user_eight"], team=self.team)
        _create_event(event="step one", distinct_id="user_eight", team=self.team, timestamp=now.strftime(FORMAT_TIME))
        _create_event(
            event="step two",
            distinct_id="user_eight",
            team=self.team,
            timestamp=(now + timedelta(minutes=1)).strftime(FORMAT_TIME),
        )
        _create_event(
            event="step three",
            distinct_id="user_eight",
            team=self.team,
            timestamp=(now + timedelta(minutes=2)).strftime(FORMAT_TIME),
        )

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": (now - timedelta(1)).strftime(FORMAT_TIME),
                "date_to": now.strftime(FORMAT_TIME_DAY_END),
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()

        self.assertEqual(len(results), 2)

        day = results[0]  # yesterday
        self.assertEqual(day["entered_count"], 0)
        self.assertEqual(day["completed_count"], 0)
        self.assertEqual(day["conversion_rate"], 0)
        self.assertEqual(
            day["timestamp"].replace(tzinfo=pytz.UTC),
            (datetime(now.year, now.month, now.day) - timedelta(1)).replace(tzinfo=pytz.UTC),
        )
        self.assertEqual(day["is_period_final"], True)  # this window can't be affected anymore

        day = results[1]  # today
        self.assertEqual(day["entered_count"], 1)
        self.assertEqual(day["completed_count"], 1)
        self.assertEqual(day["conversion_rate"], 100)
        self.assertEqual(
            day["timestamp"].replace(tzinfo=pytz.UTC), datetime(now.year, now.month, now.day).replace(tzinfo=pytz.UTC)
        )
        self.assertEqual(day["is_period_final"], False)  # events coming in now may stil affect this

    def test_two_runs_by_single_user_in_one_period(self):
        _create_person(distinct_ids=["user_one"], team=self.team)

        # 1st full run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")

        # 2nd full run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 13:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 14:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 15:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-01 23:59:59",
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()

        self.assertEqual(len(results), 1)

        day = results[0]  # 2021-05-01
        self.assertEqual(day["entered_count"], 1)
        self.assertEqual(day["completed_count"], 1)
        self.assertEqual(day["conversion_rate"], 100)
        self.assertEqual(day["is_period_final"], True)

    def test_steps_performed_in_period_but_in_reverse(self):
        _create_person(distinct_ids=["user_one"], team=self.team)

        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 03:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-01 23:59:59",
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team).perform_query()

        self.assertEqual(len(results), 1)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["entered_count"], 1)
        self.assertEqual(day_1["completed_count"], 0)
        self.assertEqual(day_1["conversion_rate"], 0)
        self.assertEqual(day_1["is_period_final"], True)
