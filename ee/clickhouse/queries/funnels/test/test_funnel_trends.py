from datetime import date, datetime, timedelta
from uuid import uuid4

import pytz
from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels import ClickhouseFunnel, ClickhouseFunnelStrict, ClickhouseFunnelUnordered
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.queries.funnels.funnel_trends_persons import ClickhouseFunnelTrendsPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.cohort import Cohort
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

    def _get_people_at_step(self, filter, entrance_period_start, drop_off, funnel_class=ClickhouseFunnel):
        person_filter = filter.with_data({"entrance_period_start": entrance_period_start, "drop_off": drop_off})
        return ClickhouseFunnelTrendsPersons(person_filter, self.team, funnel_class).run()

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

        funnel_trends = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)
        results = funnel_trends._exec_query()
        formatted_results = funnel_trends._format_results(results)

        self.assertEqual(len(results), 7)
        self.assertEqual(formatted_results[0]["days"][0], "2021-06-07")

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
        funnel_trends = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)
        results = funnel_trends._exec_query()

        self.assertEqual(
            results,
            [
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 1,
                    "timestamp": datetime(2021, 6, 7, 0, 0).replace(tzinfo=pytz.UTC),
                },
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 8, 0, 0).replace(tzinfo=pytz.UTC),
                },
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 9, 0, 0).replace(tzinfo=pytz.UTC),
                },
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 10, 0, 0).replace(tzinfo=pytz.UTC),
                },
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 11, 0, 0).replace(tzinfo=pytz.UTC),
                },
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 12, 0, 0).replace(tzinfo=pytz.UTC),
                },
                {
                    "reached_to_step_count": 0,
                    "is_period_final": True,
                    "conversion_rate": 0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 13, 0, 0).replace(tzinfo=pytz.UTC),
                },
            ],
        )

        # 1 user who dropped off starting 2021-06-07
        funnel_trends_persons_existent_dropped_off_results, _ = self._get_people_at_step(
            filter, "2021-06-07 00:00:00", True
        )

        self.assertEqual(
            len(funnel_trends_persons_existent_dropped_off_results), 1,
        )
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results], [["user a"]],
        )

        # No users converted 2021-06-07
        funnel_trends_persons_nonexistent_converted_results, _ = self._get_people_at_step(
            filter, "2021-06-07 00:00:00", False
        )

        self.assertEqual(
            len(funnel_trends_persons_nonexistent_converted_results), 0,
        )

        # No users dropped off 2021-06-08
        funnel_trends_persons_nonexistent_converted_results, _ = self._get_people_at_step(
            filter, "2021-06-08 00:00:00", True
        )

        self.assertEqual(
            len(funnel_trends_persons_nonexistent_converted_results), 0,
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
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()
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
        _create_person(distinct_ids=["user_one"], team=self.team)

        # full run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")

        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()
        self.assertEqual(7, len(results))

        persons, _ = self._get_people_at_step(filter, "2021-05-01 00:00:00", False)

        self.assertEqual(
            [person["distinct_ids"] for person in persons], [["user_one"]],
        )

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

        _create_person(distinct_ids=["user_one"], team=self.team)

        # full run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")

        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()
        persons, _ = self._get_people_at_step(filter, "2021-04-25 00:00:00", False)

        self.assertEqual(2, len(results))
        self.assertEqual(
            [person["distinct_ids"] for person in persons], [["user_one"]],
        )

    def test_month_interval(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "month",
                "date_from": "2020-01-01 00:00:00",
                "date_to": "2020-07-01 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        _create_person(distinct_ids=["user_one"], team=self.team)

        # full run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2020-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2020-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2020-05-01 02:00:00")

        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()
        self.assertEqual(
            results,
            [
                {
                    "conversion_rate": 0.0,
                    "is_period_final": True,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 1, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "is_period_final": True,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 2, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "is_period_final": True,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 3, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "is_period_final": True,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 4, 1),
                },
                {
                    "conversion_rate": 100.0,
                    "is_period_final": True,
                    "reached_from_step_count": 1,
                    "reached_to_step_count": 1,
                    "timestamp": date(2020, 5, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "is_period_final": True,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 6, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "is_period_final": True,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 7, 1),
                },
            ],
        )

        persons, _ = self._get_people_at_step(filter, "2020-05-01 00:00:00", False)

        self.assertEqual(
            [person["distinct_ids"] for person in persons], [["user_one"]],
        )

    def test_all_date_range(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "all",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        _create_person(distinct_ids=["user_one"], team=self.team)

        # full run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")

        with freeze_time("2021-05-20T13:01:01Z"):
            results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()
        self.assertEqual(20, len(results))

        persons, _ = self._get_people_at_step(filter, "2021-05-01 00:00:00", False)

        self.assertEqual(
            [person["distinct_ids"] for person in persons], [["user_one"]],
        )

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
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        saturday = results[0]  # 5/1
        self.assertEqual(3, saturday["reached_to_step_count"])
        self.assertEqual(3, saturday["reached_from_step_count"])
        self.assertEqual(100, saturday["conversion_rate"])
        self.assertEqual(True, saturday["is_period_final"])

        sunday = results[1]  # 5/2
        self.assertEqual(0, sunday["reached_to_step_count"])
        self.assertEqual(2, sunday["reached_from_step_count"])
        self.assertEqual(0, sunday["conversion_rate"])
        self.assertEqual(True, sunday["is_period_final"])

        monday = results[2]  # 5/3
        self.assertEqual(0, monday["reached_to_step_count"])
        self.assertEqual(0, monday["reached_from_step_count"])
        self.assertEqual(0, monday["conversion_rate"])
        self.assertEqual(True, monday["is_period_final"])

        tuesday = results[3]  # 5/4
        self.assertEqual(0, tuesday["reached_to_step_count"])
        self.assertEqual(0, tuesday["reached_from_step_count"])
        self.assertEqual(0, tuesday["conversion_rate"])
        self.assertEqual(True, tuesday["is_period_final"])

        wednesday = results[4]  # 5/5
        self.assertEqual(0, wednesday["reached_to_step_count"])
        self.assertEqual(0, wednesday["reached_from_step_count"])
        self.assertEqual(0, wednesday["conversion_rate"])
        self.assertEqual(True, wednesday["is_period_final"])

        thursday = results[5]  # 5/6
        self.assertEqual(0, thursday["reached_to_step_count"])
        self.assertEqual(1, thursday["reached_from_step_count"])
        self.assertEqual(0, thursday["conversion_rate"])
        self.assertEqual(True, thursday["is_period_final"])

        friday = results[6]  # 5/7
        self.assertEqual(0, friday["reached_to_step_count"])
        self.assertEqual(0, friday["reached_from_step_count"])
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
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        saturday = results[0]  # 5/1
        self.assertEqual(1, saturday["reached_to_step_count"])
        self.assertEqual(3, saturday["reached_from_step_count"])
        self.assertEqual(33.33, saturday["conversion_rate"])
        self.assertEqual(True, saturday["is_period_final"])

        sunday = results[1]  # 5/2
        self.assertEqual(0, sunday["reached_to_step_count"])
        self.assertEqual(2, sunday["reached_from_step_count"])
        self.assertEqual(0, sunday["conversion_rate"])
        self.assertEqual(True, sunday["is_period_final"])

        monday = results[2]  # 5/3
        self.assertEqual(0, monday["reached_to_step_count"])
        self.assertEqual(0, monday["reached_from_step_count"])
        self.assertEqual(0, monday["conversion_rate"])
        self.assertEqual(True, monday["is_period_final"])

        tuesday = results[3]  # 5/4
        self.assertEqual(0, tuesday["reached_to_step_count"])
        self.assertEqual(0, tuesday["reached_from_step_count"])
        self.assertEqual(0, tuesday["conversion_rate"])
        self.assertEqual(True, tuesday["is_period_final"])

        wednesday = results[4]  # 5/5
        self.assertEqual(0, wednesday["reached_to_step_count"])
        self.assertEqual(0, wednesday["reached_from_step_count"])
        self.assertEqual(0, wednesday["conversion_rate"])
        self.assertEqual(True, wednesday["is_period_final"])

        thursday = results[5]  # 5/6
        self.assertEqual(0, thursday["reached_to_step_count"])
        self.assertEqual(1, thursday["reached_from_step_count"])
        self.assertEqual(0, thursday["conversion_rate"])
        self.assertEqual(True, thursday["is_period_final"])

        friday = results[6]  # 5/7
        self.assertEqual(0, friday["reached_to_step_count"])
        self.assertEqual(0, friday["reached_from_step_count"])
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
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        self.assertEqual(len(results), 2)

        day = results[0]  # yesterday
        self.assertEqual(day["reached_from_step_count"], 0)
        self.assertEqual(day["reached_to_step_count"], 0)
        self.assertEqual(day["conversion_rate"], 0)
        self.assertEqual(
            day["timestamp"].replace(tzinfo=pytz.UTC),
            (datetime(now.year, now.month, now.day) - timedelta(1)).replace(tzinfo=pytz.UTC),
        )
        self.assertEqual(day["is_period_final"], True)  # this window can't be affected anymore

        day = results[1]  # today
        self.assertEqual(day["reached_from_step_count"], 1)
        self.assertEqual(day["reached_to_step_count"], 1)
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
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        self.assertEqual(len(results), 1)

        day = results[0]  # 2021-05-01
        self.assertEqual(day["reached_from_step_count"], 1)
        self.assertEqual(day["reached_to_step_count"], 1)
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
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        self.assertEqual(len(results), 1)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 0)
        self.assertEqual(day_1["conversion_rate"], 0)
        self.assertEqual(day_1["is_period_final"], True)

    def test_one_person_in_multiple_periods_and_windows(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)

        # 1st user's 1st complete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 03:00:00")

        # 1st user's incomplete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-03 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 02:00:00")

        # 2nd user's incomplete run
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-04 18:00:00")

        # 1st user's 2nd complete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-04 11:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-04 12:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-04 13:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-04 23:59:59",
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        self.assertEqual(len(results), 4)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)
        self.assertEqual(day_1["is_period_final"], True)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 0)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)
        self.assertEqual(day_2["is_period_final"], True)

        day_3 = results[2]  # 2021-05-03
        self.assertEqual(day_3["reached_from_step_count"], 1)
        self.assertEqual(day_3["reached_to_step_count"], 0)
        self.assertEqual(day_3["conversion_rate"], 0)
        self.assertEqual(day_3["is_period_final"], True)

        day_4 = results[3]  # 2021-05-04
        self.assertEqual(day_4["reached_from_step_count"], 2)
        self.assertEqual(day_4["reached_to_step_count"], 1)
        self.assertEqual(day_4["conversion_rate"], 50)
        self.assertEqual(day_4["is_period_final"], True)

        # 1 user who dropped off starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results, _ = self._get_people_at_step(
            filter, "2021-05-04 00:00:00", True
        )

        self.assertEqual(
            len(funnel_trends_persons_existent_dropped_off_results), 1,
        )
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results], [["user_two"]],
        )

        # 1 user who converted starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results, _ = self._get_people_at_step(
            filter, "2021-05-04 00:00:00", False
        )

        self.assertEqual(
            len(funnel_trends_persons_existent_dropped_off_results), 1,
        )
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results], [["user_one"]],
        )

    def test_from_second_step(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_person(distinct_ids=["user_three"], team=self.team)
        _create_person(distinct_ids=["user_four"], team=self.team)

        # 1st user's complete run - should fall into the 2021-05-01 bucket even though counting only from 2nd step
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-02 02:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-02 03:00:00")

        # 2nd user's incomplete run - should not count at all since not reaching 2nd step
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-01 01:00:00")

        # 3rd user's incomplete run - should not count at all since reaching 2nd step BUT not the 1st one
        _create_event(event="step two", distinct_id="user_three", team=self.team, timestamp="2021-05-02 02:00:00")
        _create_event(event="step three", distinct_id="user_three", team=self.team, timestamp="2021-05-02 03:00:00")

        # 4th user's incomplete run - should fall into the 2021-05-02 bucket as entered but not completed
        _create_event(event="step one", distinct_id="user_four", team=self.team, timestamp="2021-05-02 01:00:00")
        _create_event(event="step two", distinct_id="user_four", team=self.team, timestamp="2021-05-02 02:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-02 23:59:59",
                "funnel_window_days": 3,
                "funnel_from_step": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        self.assertEqual(len(results), 2)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)
        self.assertEqual(day_1["is_period_final"], True)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 1)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)
        self.assertEqual(day_2["is_period_final"], True)

    def test_to_second_step(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_person(distinct_ids=["user_three"], team=self.team)
        _create_person(distinct_ids=["user_four"], team=self.team)

        # 1st user's complete run - should fall into the 2021-05-01 bucket
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-02 02:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-02 03:00:00")

        # 2nd user's incomplete run - should count as incomplete
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-01 01:00:00")

        # 3rd user's incomplete run - should not count at all since reaching 2nd step BUT not the 1st one
        _create_event(event="step two", distinct_id="user_three", team=self.team, timestamp="2021-05-02 02:00:00")
        _create_event(event="step three", distinct_id="user_three", team=self.team, timestamp="2021-05-02 03:00:00")

        # 4th user's incomplete run - should fall into the 2021-05-02 bucket as entered and completed
        _create_event(event="step one", distinct_id="user_four", team=self.team, timestamp="2021-05-02 01:00:00")
        _create_event(event="step two", distinct_id="user_four", team=self.team, timestamp="2021-05-02 02:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-02 23:59:59",
                "funnel_window_days": 3,
                "funnel_to_step": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)._exec_query()

        self.assertEqual(len(results), 2)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 2)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 50)
        self.assertEqual(day_1["is_period_final"], True)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 1)
        self.assertEqual(day_2["reached_to_step_count"], 1)
        self.assertEqual(day_2["conversion_rate"], 100)
        self.assertEqual(day_2["is_period_final"], True)

    def test_one_person_in_multiple_periods_and_windows_in_unordered_funnel(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)

        # 1st user's 1st complete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 03:00:00")

        # 1st user's incomplete run
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 01:00:00")
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-03 02:00:00")

        # 2nd user's incomplete run
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-04 18:00:00")

        # 1st user's 2nd complete run
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-04 11:00:00")
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-04 12:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-04 13:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-04 23:59:59",
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnelUnordered)._exec_query()

        self.assertEqual(len(results), 4)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)
        self.assertEqual(day_1["is_period_final"], True)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 0)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)
        self.assertEqual(day_2["is_period_final"], True)

        day_3 = results[2]  # 2021-05-03
        self.assertEqual(day_3["reached_from_step_count"], 1)
        self.assertEqual(day_3["reached_to_step_count"], 0)
        self.assertEqual(day_3["conversion_rate"], 0)
        self.assertEqual(day_3["is_period_final"], True)

        day_4 = results[3]  # 2021-05-04
        self.assertEqual(day_4["reached_from_step_count"], 2)
        self.assertEqual(day_4["reached_to_step_count"], 1)
        self.assertEqual(day_4["conversion_rate"], 50)
        self.assertEqual(day_4["is_period_final"], True)

        # 1 user who dropped off starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results, _ = self._get_people_at_step(
            filter, "2021-05-04 00:00:00", True, ClickhouseFunnelUnordered
        )

        self.assertEqual(
            len(funnel_trends_persons_existent_dropped_off_results), 1,
        )
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results], [["user_two"]],
        )

        # 1 user who converted starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results, _ = self._get_people_at_step(
            filter, "2021-05-04 00:00:00", False, ClickhouseFunnelUnordered
        )

        self.assertEqual(
            len(funnel_trends_persons_existent_dropped_off_results), 1,
        )
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results], [["user_one"]],
        )

    def test_one_person_in_multiple_periods_and_windows_in_strict_funnel(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)

        # 1st user's 1st complete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-01 02:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-01 03:00:00")

        # 1st user's incomplete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-03 01:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 02:00:00")
        # broken because strict
        _create_event(event="blah", distinct_id="user_one", team=self.team, timestamp="2021-05-03 02:30:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-03 03:00:00")

        # 2nd user's incomplete run
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-04 18:00:00")
        # broken because strict
        _create_event(event="blah", distinct_id="user_two", team=self.team, timestamp="2021-05-04 18:20:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 19:00:00")

        # 1st user's 2nd complete run
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-04 11:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-04 12:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-04 13:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-04 23:59:59",
                "funnel_window_days": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )
        results = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnelStrict)._exec_query()

        self.assertEqual(len(results), 4)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)
        self.assertEqual(day_1["is_period_final"], True)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 0)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)
        self.assertEqual(day_2["is_period_final"], True)

        day_3 = results[2]  # 2021-05-03
        self.assertEqual(day_3["reached_from_step_count"], 1)
        self.assertEqual(day_3["reached_to_step_count"], 0)
        self.assertEqual(day_3["conversion_rate"], 0)
        self.assertEqual(day_3["is_period_final"], True)

        day_4 = results[3]  # 2021-05-04
        self.assertEqual(day_4["reached_from_step_count"], 2)
        self.assertEqual(day_4["reached_to_step_count"], 1)
        self.assertEqual(day_4["conversion_rate"], 50)
        self.assertEqual(day_4["is_period_final"], True)

    def test_funnel_step_breakdown_event(self):
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_event(
            event="step one",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_event(
            event="step one",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_person(distinct_ids=["user_three"], team=self.team)
        _create_event(
            event="step one",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step two",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-04 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step three",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Safari"},
        )

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "breakdown_type": "event",
                "breakdown": "$browser",
            }
        )
        funnel_trends = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)
        result = funnel_trends.run()

        self.assertEqual(len(result), 2)

        for res in result:
            if res["breakdown_value"] == "Chrome":
                self.assertEqual(res["data"], [100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            elif res["breakdown_value"] == "Safari":
                self.assertEqual(res["data"], [0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            else:
                self.fail(msg="Invalid breakdown value")

    def test_funnel_step_breakdown_person(self):
        _create_person(
            distinct_ids=["user_one"], team=self.team, properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step one",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_person(
            distinct_ids=["user_two"], team=self.team, properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step one",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_person(
            distinct_ids=["user_three"], team=self.team, properties={"$browser": "Safari"},
        )
        _create_event(
            event="step one",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step two",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-04 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step three",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Safari"},
        )

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "breakdown_type": "person",
                "breakdown": "$browser",
            }
        )
        funnel_trends = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)
        result = funnel_trends.run()

        self.assertEqual(len(result), 2)

        for res in result:
            if res["breakdown_value"] == "Chrome":
                self.assertEqual(res["data"], [100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            elif res["breakdown_value"] == "Safari":
                self.assertEqual(res["data"], [0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            else:
                self.fail(msg="Invalid breakdown value")

    def test_funnel_trend_cohort_breakdown(self):
        _create_person(
            distinct_ids=["user_one"], team=self.team, properties={"key": "value"},
        )
        _create_event(
            event="step one",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_person(
            distinct_ids=["user_two"], team=self.team, properties={"key": "value"},
        )
        _create_event(
            event="step one",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_person(
            distinct_ids=["user_three"], team=self.team, properties={"$browser": "Safari"},
        )
        _create_event(
            event="step one",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step two",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-04 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step three",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Safari"},
        )

        cohort = Cohort.objects.create(team=self.team, name="test_cohort", groups=[{"properties": {"key": "value"}}])
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-13 23:59:59",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "breakdown_type": "cohort",
                "breakdown": [cohort.pk],
            }
        )
        funnel_trends = ClickhouseFunnelTrends(filter, self.team, ClickhouseFunnel)

        result = funnel_trends.run()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["data"], [100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
