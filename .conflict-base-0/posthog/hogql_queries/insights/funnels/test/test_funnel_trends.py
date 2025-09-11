from datetime import date, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from freezegun.api import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelsQueryResponse,
    IntervalType,
    PropertyOperator,
)

from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR, FunnelOrderType, FunnelVizType
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models.cohort.cohort import Cohort
from posthog.models.filters import Filter
from posthog.queries.funnels.funnel_trends_persons import ClickhouseFunnelTrendsActors
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d %H:%M:%S"
FORMAT_TIME_DAY_END = "%Y-%m-%d 23:59:59"


class BaseTestFunnelTrends(ClickhouseTestMixin, APIBaseTest):
    __test__ = False
    maxDiff = None

    def _get_actors_at_step(self, filter, entrance_period_start, drop_off):
        filter = Filter(data=filter, team=self.team)
        person_filter = filter.shallow_clone({"entrance_period_start": entrance_period_start, "drop_off": drop_off})
        funnel_query_builder = ClickhouseFunnelTrendsActors(person_filter, self.team)
        _, serialized_result, _ = funnel_query_builder.get_actors()

        return serialized_result

    def _create_sample_data(self):
        # five people, three steps
        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                ],
                "user_three": [{"event": "step one", "timestamp": datetime(2021, 5, 6)}],
                "user_four": [{"event": "step none", "timestamp": datetime(2021, 5, 6)}],
                "user_five": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 3)},
                ],
                "user_six": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_seven": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                ],
                "user_eight": [],
            },
            self.team,
        )

    def test_no_event_in_period(self):
        journeys_for(
            {"user a": [{"event": "Step one", "timestamp": datetime(2021, 6, 6, 21)}]},
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        # funnel_trends = ClickhouseFunnelTrends(filter, self.team)
        # results = funnel_trends._exec_query()
        # formatted_results = funnel_trends._format_results(results)
        query = cast(FunnelsQuery, filter_to_query(filters))
        runner = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True)
        results = runner.calculate().results
        formatted_results = runner.funnel_class._format_summarized_results(results)

        self.assertEqual(len(results), 7)
        self.assertEqual(formatted_results[0]["days"][0], "2021-06-07")

    @parameterized.expand(["US/Pacific", "UTC"])
    def test_only_one_user_reached_one_step(self, timezone):
        self.team.timezone = timezone
        self.team.save()

        journeys_for(
            {"user a": [{"event": "step one", "timestamp": datetime(2021, 6, 7, 19)}]},
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(
            results,
            [
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 1,
                    "timestamp": datetime(2021, 6, 7, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 8, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 9, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 10, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 11, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 12, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
                {
                    "reached_to_step_count": 0,
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "timestamp": datetime(2021, 6, 13, 0, 0).replace(tzinfo=ZoneInfo(timezone)),
                },
            ],
        )

        # 1 user who dropped off starting 2021-06-07
        funnel_trends_persons_existent_dropped_off_results = self._get_actors_at_step(
            filters, "2021-06-07 00:00:00", True
        )

        self.assertEqual(len(funnel_trends_persons_existent_dropped_off_results), 1)
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results],
            [["user a"]],
        )

        # No users converted 2021-06-07
        funnel_trends_persons_nonexistent_converted_results = self._get_actors_at_step(
            filters, "2021-06-07 00:00:00", False
        )

        self.assertEqual(len(funnel_trends_persons_nonexistent_converted_results), 0)

        # No users dropped off 2021-06-08
        funnel_trends_persons_nonexistent_converted_results = self._get_actors_at_step(
            filters, "2021-06-08 00:00:00", True
        )

        self.assertEqual(len(funnel_trends_persons_nonexistent_converted_results), 0)

    # minute, hour, day, week, month
    def test_hour_interval(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "hour",
            "date_from": "2021-05-01 00:00:00",
            "funnel_window_interval": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        with freeze_time("2021-05-06T23:40:59Z"):
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 144)

    def test_day_interval(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 2)},
                ]
            },
            self.team,
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(7, len(results))

        persons = self._get_actors_at_step(filters, "2021-05-01 00:00:00", False)

        self.assertEqual([person["distinct_ids"] for person in persons], [["user_one"]])

    @snapshot_clickhouse_queries
    def test_week_interval(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 2)},
                ]
            },
            self.team,
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
        persons = self._get_actors_at_step(filters, "2021-04-25 00:00:00", False)

        self.assertEqual(2, len(results))
        self.assertEqual([person["distinct_ids"] for person in persons], [["user_one"]])

    @parameterized.expand(["US/Pacific", "UTC"])
    def test_month_interval(self, timezone):
        self.team.timezone = timezone
        self.team.save()

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2020, 5, 1, 0)},
                    {"event": "step two", "timestamp": datetime(2020, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2020, 5, 1, 2)},
                ]
            },
            self.team,
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(
            results,
            [
                {
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 1, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 2, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 3, 1),
                },
                {
                    "conversion_rate": 100.0 if timezone == "US/Pacific" else 0.0,
                    "reached_from_step_count": 1 if timezone == "US/Pacific" else 0,
                    "reached_to_step_count": 1 if timezone == "US/Pacific" else 0,
                    "timestamp": date(2020, 4, 1),
                },
                {
                    "conversion_rate": 100.0 if timezone == "UTC" else 0.0,
                    "reached_from_step_count": 1 if timezone == "UTC" else 0,
                    "reached_to_step_count": 1 if timezone == "UTC" else 0,
                    "timestamp": date(2020, 5, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 6, 1),
                },
                {
                    "conversion_rate": 0.0,
                    "reached_from_step_count": 0,
                    "reached_to_step_count": 0,
                    "timestamp": date(2020, 7, 1),
                },
            ],
        )
        entrance_period_start = "2020-05-01 00:00:00" if timezone == "UTC" else "2020-04-01 00:00:00"
        persons = self._get_actors_at_step(filters, entrance_period_start, False)

        self.assertEqual([person["distinct_ids"] for person in persons], [["user_one"]])

    def test_all_date_range(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 2)},
                ]
            },
            self.team,
        )

        with freeze_time("2021-05-20T13:01:01Z"):
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(20, len(results))

        persons = self._get_actors_at_step(filters, "2021-05-01 00:00:00", False)

        self.assertEqual([person["distinct_ids"] for person in persons], [["user_one"]])

    def test_all_results_for_day_interval(self):
        self._create_sample_data()

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        saturday = results[0]  # 5/1
        self.assertEqual(3, saturday["reached_to_step_count"])
        self.assertEqual(3, saturday["reached_from_step_count"])
        self.assertEqual(100, saturday["conversion_rate"])

        sunday = results[1]  # 5/2
        self.assertEqual(0, sunday["reached_to_step_count"])
        self.assertEqual(2, sunday["reached_from_step_count"])
        self.assertEqual(0, sunday["conversion_rate"])

        monday = results[2]  # 5/3
        self.assertEqual(0, monday["reached_to_step_count"])
        self.assertEqual(0, monday["reached_from_step_count"])
        self.assertEqual(0, monday["conversion_rate"])

        tuesday = results[3]  # 5/4
        self.assertEqual(0, tuesday["reached_to_step_count"])
        self.assertEqual(0, tuesday["reached_from_step_count"])
        self.assertEqual(0, tuesday["conversion_rate"])

        wednesday = results[4]  # 5/5
        self.assertEqual(0, wednesday["reached_to_step_count"])
        self.assertEqual(0, wednesday["reached_from_step_count"])
        self.assertEqual(0, wednesday["conversion_rate"])

        thursday = results[5]  # 5/6
        self.assertEqual(0, thursday["reached_to_step_count"])
        self.assertEqual(1, thursday["reached_from_step_count"])
        self.assertEqual(0, thursday["conversion_rate"])

        friday = results[6]  # 5/7
        self.assertEqual(0, friday["reached_to_step_count"])
        self.assertEqual(0, friday["reached_from_step_count"])
        self.assertEqual(0, friday["conversion_rate"])

    def test_window_size_one_day(self):
        self._create_sample_data()

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        saturday = results[0]  # 5/1
        self.assertEqual(1, saturday["reached_to_step_count"])
        self.assertEqual(3, saturday["reached_from_step_count"])
        self.assertEqual(33.33, saturday["conversion_rate"])

        sunday = results[1]  # 5/2
        self.assertEqual(0, sunday["reached_to_step_count"])
        self.assertEqual(2, sunday["reached_from_step_count"])
        self.assertEqual(0, sunday["conversion_rate"])

        monday = results[2]  # 5/3
        self.assertEqual(0, monday["reached_to_step_count"])
        self.assertEqual(0, monday["reached_from_step_count"])
        self.assertEqual(0, monday["conversion_rate"])

        tuesday = results[3]  # 5/4
        self.assertEqual(0, tuesday["reached_to_step_count"])
        self.assertEqual(0, tuesday["reached_from_step_count"])
        self.assertEqual(0, tuesday["conversion_rate"])

        wednesday = results[4]  # 5/5
        self.assertEqual(0, wednesday["reached_to_step_count"])
        self.assertEqual(0, wednesday["reached_from_step_count"])
        self.assertEqual(0, wednesday["conversion_rate"])

        thursday = results[5]  # 5/6
        self.assertEqual(0, thursday["reached_to_step_count"])
        self.assertEqual(1, thursday["reached_from_step_count"])
        self.assertEqual(0, thursday["conversion_rate"])

        friday = results[6]  # 5/7
        self.assertEqual(0, friday["reached_to_step_count"])
        self.assertEqual(0, friday["reached_from_step_count"])
        self.assertEqual(0, friday["conversion_rate"])

    def test_period_not_final(self):
        now = datetime.now()

        journeys_for(
            {
                "user_eight": [
                    {"event": "step one", "timestamp": now},
                    {"event": "step two", "timestamp": now + timedelta(minutes=1)},
                    {"event": "step three", "timestamp": now + timedelta(minutes=2)},
                ]
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 2)

        day = results[0]  # yesterday
        self.assertEqual(day["reached_from_step_count"], 0)
        self.assertEqual(day["reached_to_step_count"], 0)
        self.assertEqual(day["conversion_rate"], 0)
        self.assertEqual(
            day["timestamp"].replace(tzinfo=ZoneInfo("UTC")),
            (datetime(now.year, now.month, now.day) - timedelta(1)).replace(tzinfo=ZoneInfo("UTC")),
        )

        day = results[1]  # today
        self.assertEqual(day["reached_from_step_count"], 1)
        self.assertEqual(day["reached_to_step_count"], 1)
        self.assertEqual(day["conversion_rate"], 100)
        self.assertEqual(
            day["timestamp"].replace(tzinfo=ZoneInfo("UTC")),
            datetime(now.year, now.month, now.day).replace(tzinfo=ZoneInfo("UTC")),
        )

    def test_two_runs_by_single_user_in_one_period(self):
        journeys_for(
            {
                "user_one": [
                    # 1st full run
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 2)},
                    # 2nd full run
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 13)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 14)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 15)},
                ]
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 1)

        day = results[0]  # 2021-05-01
        self.assertEqual(day["reached_from_step_count"], 1)
        self.assertEqual(day["reached_to_step_count"], 1)
        self.assertEqual(day["conversion_rate"], 100)

    def test_steps_performed_in_period_but_in_reverse(self):
        journeys_for(
            {
                "user_one": [
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 2)},
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 3)},
                ]
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 1)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 0)
        self.assertEqual(day_1["conversion_rate"], 0)

    def test_one_person_in_multiple_periods_and_windows(self):
        journeys_for(
            {
                "user_one": [
                    # 1st user's 1st complete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 3)},
                    # 1st user's incomplete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 3, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3, 2)},
                    # 1st user's 2nd complete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 4, 11)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4, 12)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 4, 13)},
                ],
                "user_two": [
                    # 2nd user's incomplete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 4, 18)}
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-04 23:59:59",
            "funnel_window_interval": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 4)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 0)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)

        day_3 = results[2]  # 2021-05-03
        self.assertEqual(day_3["reached_from_step_count"], 1)
        self.assertEqual(day_3["reached_to_step_count"], 0)
        self.assertEqual(day_3["conversion_rate"], 0)

        day_4 = results[3]  # 2021-05-04
        self.assertEqual(day_4["reached_from_step_count"], 2)
        self.assertEqual(day_4["reached_to_step_count"], 1)
        self.assertEqual(day_4["conversion_rate"], 50)

        # 1 user who dropped off starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results = self._get_actors_at_step(
            filters, "2021-05-04 00:00:00", True
        )

        self.assertEqual(len(funnel_trends_persons_existent_dropped_off_results), 1)
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results],
            [["user_two"]],
        )

        # 1 user who converted starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results = self._get_actors_at_step(
            filters, "2021-05-04 00:00:00", False
        )

        self.assertEqual(len(funnel_trends_persons_existent_dropped_off_results), 1)
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results],
            [["user_one"]],
        )

    def test_from_second_step(self):
        journeys_for(
            {
                "user_one": [
                    # 1st user's complete run - should fall into the 2021-05-01 bucket even though counting only from 2nd step
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 2, 3)},
                ],
                "user_two": [
                    # 2nd user's incomplete run - should not count at all since not reaching 2nd step
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)}
                ],
                "user_three": [
                    # 3rd user's incomplete run - should not count at all since reaching 2nd step BUT not the 1st one
                    {"event": "step two", "timestamp": datetime(2021, 5, 2, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 2, 3)},
                ],
                "user_four": [
                    # 4th user's incomplete run - should fall into the 2021-05-02 bucket as entered but not completed
                    {"event": "step one", "timestamp": datetime(2021, 5, 2, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2, 2)},
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 2)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 1)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)

    def test_to_second_step(self):
        journeys_for(
            {
                "user_one": [
                    # 1st user's complete run - should fall into the 2021-05-01 bucket
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 2, 3)},
                ],
                "user_two": [
                    # 2nd user's incomplete run - should count as incomplete
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)}
                ],
                "user_three": [
                    # 3rd user's incomplete run - should not count at all since reaching 2nd step BUT not the 1st one
                    {"event": "step two", "timestamp": datetime(2021, 5, 2, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 2, 3)},
                ],
                "user_four": [
                    # 4th user's incomplete run - should fall into the 2021-05-02 bucket as entered and completed
                    {"event": "step one", "timestamp": datetime(2021, 5, 2, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2, 2)},
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 2)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 2)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 50)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 1)
        self.assertEqual(day_2["reached_to_step_count"], 1)
        self.assertEqual(day_2["conversion_rate"], 100)

    def test_one_person_in_multiple_periods_and_windows_in_unordered_funnel(self):
        journeys_for(
            {
                "user_one": [
                    # 1st user's 1st complete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 3)},
                    # 1st user's incomplete run
                    {"event": "step two", "timestamp": datetime(2021, 5, 3, 1)},
                    {"event": "step one", "timestamp": datetime(2021, 5, 3, 2)},
                    # 1st user's 2nd complete run
                    {"event": "step three", "timestamp": datetime(2021, 5, 4, 11)},
                    {"event": "step one", "timestamp": datetime(2021, 5, 4, 12)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4, 13)},
                ],
                "user_two": [
                    # 2nd user's incomplete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 4, 18)}
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-04 23:59:59",
            "funnel_window_interval": 1,
            "funnel_order_type": FunnelOrderType.UNORDERED,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 4)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 0)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)

        day_3 = results[2]  # 2021-05-03
        self.assertEqual(day_3["reached_from_step_count"], 1)
        self.assertEqual(day_3["reached_to_step_count"], 0)
        self.assertEqual(day_3["conversion_rate"], 0)

        day_4 = results[3]  # 2021-05-04
        self.assertEqual(day_4["reached_from_step_count"], 2)
        self.assertEqual(day_4["reached_to_step_count"], 1)
        self.assertEqual(day_4["conversion_rate"], 50)

        # 1 user who dropped off starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results = self._get_actors_at_step(
            filters, "2021-05-04 00:00:00", True
        )

        self.assertEqual(len(funnel_trends_persons_existent_dropped_off_results), 1)
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results],
            [["user_two"]],
        )

        # 1 user who converted starting # 2021-05-04
        funnel_trends_persons_existent_dropped_off_results = self._get_actors_at_step(
            filters, "2021-05-04 00:00:00", False
        )

        self.assertEqual(len(funnel_trends_persons_existent_dropped_off_results), 1)
        self.assertEqual(
            [person["distinct_ids"] for person in funnel_trends_persons_existent_dropped_off_results],
            [["user_one"]],
        )

    def test_one_person_in_multiple_periods_and_windows_in_strict_funnel(self):
        journeys_for(
            {
                "user_one": [
                    # 1st user's 1st complete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 2)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 3)},
                    # 1st user's incomplete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 3, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3, 2)},
                    # broken because strict
                    {"event": "blah", "timestamp": datetime(2021, 5, 3, 2, 30)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 3, 3)},
                    # 1st user's 2nd complete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 4, 11)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4, 12)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 4, 13)},
                ],
                "user_two": [
                    # 2nd user's incomplete run
                    {"event": "step one", "timestamp": datetime(2021, 5, 4, 18)},
                    # broken because strict
                    {"event": "blah", "timestamp": datetime(2021, 5, 4, 18, 20)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4, 19)},
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-04 23:59:59",
            "funnel_order_type": FunnelOrderType.STRICT,
            "funnel_window_days": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 4)

        day_1 = results[0]  # 2021-05-01
        self.assertEqual(day_1["reached_from_step_count"], 1)
        self.assertEqual(day_1["reached_to_step_count"], 1)
        self.assertEqual(day_1["conversion_rate"], 100)

        day_2 = results[1]  # 2021-05-02
        self.assertEqual(day_2["reached_from_step_count"], 0)
        self.assertEqual(day_2["reached_to_step_count"], 0)
        self.assertEqual(day_2["conversion_rate"], 0)

        day_3 = results[2]  # 2021-05-03
        self.assertEqual(day_3["reached_from_step_count"], 1)
        self.assertEqual(day_3["reached_to_step_count"], 0)
        self.assertEqual(day_3["conversion_rate"], 0)

        day_4 = results[3]  # 2021-05-04
        self.assertEqual(day_4["reached_from_step_count"], 2)
        self.assertEqual(day_4["reached_to_step_count"], 1)
        self.assertEqual(day_4["conversion_rate"], 50)

    def test_funnel_step_breakdown_event(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 5),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "user_two": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 2),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 5),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "user_three": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 4),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 5),
                        "properties": {"$browser": "Safari"},
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 2)

        for res in results:
            if res["breakdown_value"] == ["Chrome"]:
                self.assertEqual(
                    res["data"],
                    [
                        100.0,
                        100.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                )
            elif res["breakdown_value"] == ["Safari"]:
                self.assertEqual(
                    res["data"],
                    [0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                )
            else:
                self.fail(msg="Invalid breakdown value")

    def test_funnel_step_breakdown_empty(self):
        attribution_types = [
            "all_events",
            "first_touch",
            "last_touch",
            "step",
        ]
        for attribution_type in attribution_types:
            journeys_for(
                {
                    "user_one": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 1),
                            "properties": {"$browser": "Chrome"},
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 3),
                            "properties": {"$browser": "Chrome"},
                        },
                        {
                            "event": "step three",
                            "timestamp": datetime(2021, 5, 5),
                            "properties": {"$browser": "Chrome"},
                        },
                    ],
                    "user_two": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 2),
                            "properties": {"$browser": "Chrome"},
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 3),
                            "properties": {"$browser": "Chrome"},
                        },
                        {
                            "event": "step three",
                            "timestamp": datetime(2021, 5, 5),
                            "properties": {"$browser": "Chrome"},
                        },
                    ],
                    "user_three": [
                        {
                            "event": "step one",
                            "timestamp": datetime(2021, 5, 3),
                            "properties": {"$browser": "Safari"},
                        },
                        {
                            "event": "step two",
                            "timestamp": datetime(2021, 5, 4),
                            "properties": {"$browser": "Safari"},
                        },
                        {
                            "event": "step three",
                            "timestamp": datetime(2021, 5, 5),
                            "properties": {"$browser": "Safari"},
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "insight": INSIGHT_FUNNELS,
                "funnel_viz_type": "trends",
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
                "breakdown_type": "hogql",
                "breakdown": "IF(distinct_id = 'user_two', NULL, 'foo')",  # Simulate some empty breakdown values
                "breakdown_attribution_type": attribution_type,
            }
            if attribution_type == "step":
                filters["breakdown_attribution_value"] = 1  # Example value; adjust if needed

            query = cast(FunnelsQuery, filter_to_query(filters))
            response = FunnelsQueryRunner(query=query, team=self.team).calculate()
            results = response.results

            self.assertEqual(len(results), 2)
            # Old funnels incorrectly return None instead of empty string for empty breakdown values in these two attribution modes
            # Not worth fixing for now
            if response.isUdf or attribution_type not in ("all_events", "step"):
                self.assertEqual(results[0]["breakdown_value"], [""])
            self.assertEqual(results[0]["data"], [0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            self.assertEqual(results[1]["breakdown_value"], ["foo"])
            self.assertEqual(results[1]["data"], [100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_funnel_step_breakdown_event_with_breakdown_limit(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 5),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "user_two": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 2),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 5),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "user_three": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 4),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 5),
                        "properties": {"$browser": "Safari"},
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_days": 7,
            "breakdown_limit": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["data"],
            [
                100.0,
                100.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ],
        )
        self.assertEqual(results[0]["breakdown_value"], ["Chrome"])

    def test_funnel_step_breakdown_person(self):
        _create_person(distinct_ids=["user_one"], team=self.team, properties={"$browser": "Chrome"})
        _create_person(distinct_ids=["user_two"], team=self.team, properties={"$browser": "Chrome"})
        _create_person(
            distinct_ids=["user_three"],
            team=self.team,
            properties={"$browser": "Safari"},
        )
        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_three": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 2)

        for res in results:
            if res["breakdown_value"] == ["Chrome"]:
                self.assertEqual(
                    res["data"],
                    [
                        100.0,
                        100.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                )
            elif res["breakdown_value"] == ["Safari"]:
                self.assertEqual(
                    res["data"],
                    [0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                )
            else:
                self.fail(msg="Invalid breakdown value")

    def test_funnel_trend_cohort_breakdown(self):
        _create_person(distinct_ids=["user_one"], team=self.team, properties={"key": "value"})
        _create_person(distinct_ids=["user_two"], team=self.team, properties={"key": "value"})
        _create_person(
            distinct_ids=["user_three"],
            team=self.team,
            properties={"$browser": "Safari"},
        )

        journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 2)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
                "user_three": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 3)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 4)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                ],
            },
            self.team,
        )

        cohort = Cohort.objects.create(
            team=self.team,
            name="test_cohort",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
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

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["data"],
            [100.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )

    @snapshot_clickhouse_queries
    def test_timezones_trends(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 10),
                    },  # 04-30 in pacific
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 11),
                    },  # today in pacific
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 1, 12),
                    },  # today in pacific
                ],
                "user_two": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 1),
                    },  # 04-30 in pacific
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 2),
                    },  # 04-30 in pacific
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 1, 3),
                    },  # 04-30 in pacific
                ],
                "user_three": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 1),
                    },  # 04-30 in pacific
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 10),
                    },  # today in pacific
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 1, 11),
                    },  # today in pacific
                ],
                "user_eight": [],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-04-30 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.team.timezone = "US/Pacific"
        self.team.save()

        results_pacific = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        saturday = results[1]  # 5/1
        self.assertEqual(3, saturday["reached_to_step_count"])
        self.assertEqual(3, saturday["reached_from_step_count"])
        self.assertEqual(100.0, saturday["conversion_rate"])

        friday_pacific = results_pacific[0]
        self.assertEqual(2, friday_pacific["reached_to_step_count"])
        self.assertEqual(2, friday_pacific["reached_from_step_count"])
        self.assertEqual(100.0, friday_pacific["conversion_rate"])
        saturday_pacific = results_pacific[1]
        self.assertEqual(1, saturday_pacific["reached_to_step_count"])
        self.assertEqual(1, saturday_pacific["reached_from_step_count"])

    def test_trend_for_hour_based_conversion_window(self):
        journeys_for(
            {
                "user_one": [
                    # Converts in 2 hours
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 10)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 11)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 12)},
                ],
                "user_two": [
                    # Converts in 4 hours (not fast enough)
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 10)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 11)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 14)},
                ],
            },
            self.team,
        )
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "funnel_window_interval": 3,
            "funnel_window_interval_unit": "hour",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        with freeze_time("2021-05-06T23:40:59Z"):
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results
            conversion_rates = [row["conversion_rate"] for row in results]
            self.assertEqual(conversion_rates, [50.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_parses_breakdown_correctly(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$browser": "test''123"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$browser": "test''123"},
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 1)

    def test_short_exclusions(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "exclusion",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 31),
                    },
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 1, 0, 0),
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 1, 0, 29),
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 30,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 1)
        self.assertEqual([100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], results[0]["data"])

    def test_funnel_exclusion_no_end_event(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "funnel_window_interval": 1,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-14 00:00:00",
            "exclusions": [
                {
                    "id": "x",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        # person 1
        _create_person(distinct_ids=["person1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person1",
            timestamp="2021-05-01 01:00:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person1",
            timestamp="2021-05-01 02:00:00",
        )

        # person 2
        _create_person(distinct_ids=["person2"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person2",
            timestamp="2021-05-01 03:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person2",
            timestamp="2021-05-01 03:30:00",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="person2",
            timestamp="2021-05-01 04:00:00",
        )

        # person 3
        _create_person(distinct_ids=["person3"], team_id=self.team.pk)
        # should be discarded, even if nothing happened after x, since within conversion window
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person3",
            timestamp="2021-05-01 05:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person3",
            timestamp="2021-05-01 06:00:00",
        )

        # person 4 - outside conversion window
        _create_person(distinct_ids=["person4"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="person4",
            timestamp="2021-05-01 07:00:00",
        )
        _create_event(
            team=self.team,
            event="x",
            distinct_id="person4",
            timestamp="2021-05-02 08:00:00",
        )

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(len(results), 1)
        # person2 and person3 should be excluded, person 1 and 4 should make it
        self.assertEqual([50, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], results[0]["data"])

    def test_funnel_exclusion_multiple_possible_no_end_event1(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "exclusion",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    },
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 31),
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])

    def test_funnel_exclusion_multiple_possible_no_end_event2(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 31),
                    },
                    {
                        "event": "exclusion",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 32),
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])

    def test_funnel_exclusion_multiple_possible_no_end_event3(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    },
                    {
                        "event": "exclusion",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(0, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])

    def test_exclusion_after_goal(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 1),
            },
            {
                "event": "step three",
                "timestamp": datetime(2021, 5, 1, 0, 0, 3),
            },
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 4),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 5),
            },
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 1, 0, 0, 6),
            },
            {
                "event": "step three",
                "timestamp": datetime(2021, 5, 1, 0, 0, 7),
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 1,
                    "funnel_to_step": 2,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["reached_from_step_count"])
        self.assertEqual(1, results[0]["reached_to_step_count"])

    def test_exclusion_multiday_completion_on_first_day(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 1),
            },
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 2, 0, 0, 4),
            },
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 2, 0, 0, 5),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 2, 0, 0, 6),
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["reached_from_step_count"])
        self.assertEqual(1, results[0]["reached_to_step_count"])
        self.assertEqual(0, results[1]["reached_from_step_count"])
        self.assertEqual(0, results[1]["reached_to_step_count"])

    def test_exclusion_multiday_completion_on_second_day(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 1, 0, 0, 1),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 2),
            },
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 2, 0, 0, 4),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 2, 0, 0, 6),
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(0, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])
        self.assertEqual(1, results[1]["reached_from_step_count"])
        self.assertEqual(1, results[1]["reached_to_step_count"])

    # When there is a partial match and then an exclusion, the partial match gets dropped
    # When there is a full match and then an exclusion, the full match doesn't get dropped
    def test_exclusion_multiday_partial_first_day_exclusion_second_day(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 2, 0, 0, 30),
                    },
                    {
                        "event": "exclusion",
                        "timestamp": datetime(2021, 5, 2, 0, 0, 31),
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 2, 0, 0, 32),
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(0, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])
        self.assertEqual(0, results[1]["reached_from_step_count"])
        self.assertEqual(0, results[1]["reached_to_step_count"])

    def test_exclusion_multiday_partial_first_day_open_exclusion_second_day(self):
        journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 2, 0, 0, 30),
                    },
                    {
                        "event": "exclusion",
                        "timestamp": datetime(2021, 5, 2, 0, 0, 31),
                    },
                ],
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])
        self.assertEqual(0, results[1]["reached_from_step_count"])
        self.assertEqual(0, results[1]["reached_to_step_count"])

    def test_open_exclusion_multiday(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 1),
            },
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 2, 0, 0, 4),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 2, 0, 0, 5),
            },
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 2, 0, 0, 6),
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 1,
                    "funnel_to_step": 2,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])
        self.assertEqual(0, results[1]["reached_from_step_count"])
        self.assertEqual(0, results[1]["reached_to_step_count"])

    def test_excluded_completion(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            # Exclusion happens after time expires
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 1, 0, 0, 11),
            },
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 12),
            },
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 1, 0, 0, 13),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 14),
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(0, results[0]["reached_from_step_count"])
        self.assertEqual(0, results[0]["reached_to_step_count"])

    def test_breakdown_with_attribution(self):
        events = [
            {
                "event": "step one",
                "properties": {"$browser": "Chrome"},
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            {
                "event": "step one",
                "properties": {"$browser": "Safari"},
                "timestamp": datetime(2021, 5, 1, 0, 0, 1),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 14),
                "properties": {"$browser": "Chrome"},
            },
            {
                "event": "step one",
                "properties": {"$browser": "Chrome"},
                "timestamp": datetime(2021, 5, 2, 0, 0, 0),
            },
            {
                "event": "step two",
                "properties": {"$browser": "Safari"},
                "timestamp": datetime(2021, 5, 2, 0, 0, 1),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 2, 0, 0, 14),
                "properties": {"$browser": "Chrome"},
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-02 23:59:59",
            "funnel_window_interval": 30,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        assert 2 == len(results)
        assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
        assert [1, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]

        filters["breakdown_attribution_type"] = "all_events"
        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        assert 4 == len(results)
        assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
        assert [1, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
        assert [1, 0] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]
        assert [0, 0] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]

        filters["breakdown_attribution_type"] = "step"
        filters["breakdown_attribution_value"] = 0
        query = cast(FunnelsQuery, filter_to_query(filters))
        full_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate()
        results = full_results.results

        # Normal funnels fail on this
        if full_results.isUdf:
            assert 4 == len(results)
            assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [1, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [1, 0] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]
            assert [1, 0] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]

            filters["breakdown_attribution_type"] = "step"
            filters["breakdown_attribution_value"] = 1
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            assert 4 == len(results)
            assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [1, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]
            assert [0, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]

    def test_breakdown_with_attribution_2(self):
        events = [
            {
                "event": "step one",
                "properties": {"$browser": "Chrome"},
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                "properties": {"$browser": "Chrome"},
            },
            {
                "event": "step three",
                "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                "properties": {"$browser": "Safari"},
            },
            {
                "event": "step one",
                "properties": {"$browser": "Safari"},
                "timestamp": datetime(2021, 5, 2, 0, 0, 0),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 2, 0, 0, 1),
                "properties": {"$browser": "Safari"},
            },
            {
                "event": "step three",
                "timestamp": datetime(2021, 5, 2, 0, 0, 2),
                "properties": {"$browser": "Chrome"},
            },
        ]

        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-02 23:59:59",
            "funnel_window_interval": 30,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
            "funnel_from_step": 0,
            "funnel_to_step": 2,
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        assert 2 == len(results)
        assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
        assert [1, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]

        filters["breakdown_attribution_type"] = "all_events"
        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        assert 4 == len(results)
        assert [1, 0] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
        assert [0, 0] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
        assert [0, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]
        assert [0, 0] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]

        filters["breakdown_attribution_type"] = "step"
        filters["breakdown_attribution_value"] = 0
        query = cast(FunnelsQuery, filter_to_query(filters))
        full_results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate()
        results = full_results.results

        if full_results.isUdf:
            assert 4 == len(results)
            assert [1, 0] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [1, 0] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [0, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]
            assert [0, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]

            filters["breakdown_attribution_type"] = "step"
            filters["breakdown_attribution_value"] = 2
            query = cast(FunnelsQuery, filter_to_query(filters))
            results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

            assert 4 == len(results)
            assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [0, 1] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Chrome"]]
            assert [1, 1] == [x["reached_from_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]
            assert [1, 0] == [x["reached_to_step_count"] for x in results if x["breakdown_value"] == ["Safari"]]

    def test_exclusion_with_property_filter(self):
        journeys_for(
            {
                "user_excluded": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "exclusion",
                        "properties": {"exclude_me": "true"},
                        "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                    },
                ],
                "user_excluded_also": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "exclusion",
                        "properties": {"exclude_me": "yes"},
                        "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                    },
                ],
                "user_first_step": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    }
                ],
                "user_included": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 0),
                    },
                    {
                        "event": "exclusion",
                        "properties": {"exclude_me": "false"},
                        "timestamp": datetime(2021, 5, 1, 0, 0, 1),
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 0, 0, 2),
                    },
                ],
            },
            self.team,
        )

        query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(
                date_from="2021-05-01 00:00:00",
                date_to="2021-05-07 23:59:59",
            ),
            interval=IntervalType.DAY,
            series=[
                EventsNode(
                    kind="EventsNode",
                    event="step one",
                    name="step one",
                ),
                EventsNode(
                    kind="EventsNode",
                    event="step two",
                    name="step two",
                ),
            ],
            funnelsFilter=FunnelsFilter(
                **{
                    "funnelVizType": FunnelVizType.TRENDS,
                    "funnelWindowInterval": 10,
                    "funnelWindowIntervalUnit": FunnelConversionWindowTimeUnit.SECOND,
                    "exclusions": [
                        FunnelExclusionEventsNode(
                            kind="EventsNode",
                            event="exclusion",
                            properties=[
                                EventPropertyFilter(
                                    key="exclude_me",
                                    value="true",
                                    operator=PropertyOperator.EXACT,
                                    type="event",
                                )
                            ],
                            funnelFromStep=0,
                            funnelToStep=1,
                        ),
                        FunnelExclusionEventsNode(
                            kind="EventsNode",
                            event="exclusion",
                            properties=[
                                EventPropertyFilter(
                                    key="exclude_me",
                                    value="yes",
                                    operator=PropertyOperator.EXACT,
                                    type="event",
                                )
                            ],
                            funnelFromStep=0,
                            funnelToStep=1,
                        ),
                    ],
                }
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(len(results), 7)
        self.assertEqual(results[0]["reached_from_step_count"], 2)  # Both non-excluded users started the funnel
        self.assertEqual(results[0]["reached_to_step_count"], 1)  # Only one user converted

    def test_funnel_with_long_interval_no_first_step(self):
        # Create a person who only completes the second step of the funnel
        _create_person(distinct_ids=["only_second_step"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="added to cart",
            distinct_id="only_second_step",
            timestamp=datetime(2021, 5, 2, 0, 0, 0),
        )

        _create_person(distinct_ids=["only_first_step"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="only_first_step",
            timestamp=datetime(2021, 5, 3, 0, 0, 0),
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "events": [{"id": "user signed up", "order": 0}, {"id": "added to cart", "order": 1}],
            "funnel_window_interval": 3122064000,
            "funnel_window_interval_unit": "second",
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        # Since in funnel trends we're tracking conversion by day, not aggregated totals,
        # and the user only completes step 2 without step 1, there should be no conversions for any day
        for day_result in results[:2] + results[3:]:
            self.assertEqual(day_result["reached_from_step_count"], 0)
            self.assertEqual(day_result["reached_to_step_count"], 0)
            self.assertEqual(day_result["conversion_rate"], 0.0)

        self.assertEqual(results[2]["reached_from_step_count"], 1)
        self.assertEqual(results[2]["reached_to_step_count"], 0)

    def test_funnel_trends_with_out_of_order_completion(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 7, 19)},
                    {"event": "step three", "timestamp": datetime(2021, 6, 7, 20)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 7, 21)},
                ]
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "day",
            "date_from": "2021-06-07 00:00:00",
            "date_to": "2021-06-13 23:59:59",
            "funnel_window_days": 7,
            "funnel_from_step": 0,
            "funnel_to_step": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        runner = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True)
        results = runner.calculate().results

        self.assertEqual(len(results), 7)  # 7 days in the date range
        self.assertEqual(results[0]["reached_to_step_count"], 1)
        self.assertEqual(results[1]["reached_to_step_count"], 0)


class TestFunnelTrends(BaseTestFunnelTrends):
    __test__ = True

    def test_assert_udf_flag_is_working(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "display": TRENDS_LINEAR,
            "interval": "hour",
            "date_from": "2021-05-01 00:00:00",
            "funnel_window_interval": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = cast(FunnelsQueryResponse, FunnelsQueryRunner(query=query, team=self.team).calculate())

        self.assertFalse(results.isUdf)
