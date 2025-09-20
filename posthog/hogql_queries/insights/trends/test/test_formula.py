from typing import Optional

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest import mock

from django.test import override_settings

from posthog.schema import TrendsFilter, TrendsQuery

from posthog.constants import TRENDS_BOLD_NUMBER, TRENDS_CUMULATIVE, TRENDS_PIE
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.models import Cohort
from posthog.models.group.util import create_group
from posthog.models.utils import uuid7
from posthog.test.test_utils import create_group_type_mapping_without_created_at


@override_settings(IN_UNIT_TESTING=True)
class TestFormula(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False
    maxDiff = None

    def setUp(self):
        super().setUp()

        _create_person(
            team_id=self.team.pk,
            distinct_ids=["blabla", "anonymous_id"],
            properties={"$some_prop": "some_val"},
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )

        s1 = str(uuid7("2020-01-02T13:01:01Z", 1))
        with freeze_time("2020-01-02T13:01:01Z"):
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={
                    "xyz": 200,
                    "location": "Paris",
                    "$current_url": "http://example.org",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={
                    "xyz": 300,
                    "location": "Paris",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={
                    "xyz": 400,
                    "location": "London",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )
        with freeze_time("2020-01-03T13:01:01Z"):
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={
                    "xyz": 400,
                    "location": "London",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )
        with freeze_time("2020-01-03T13:04:01Z"):
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={
                    "xyz": 500,
                    "location": "London",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )
            _create_event(
                team=self.team,
                event="session end",
                distinct_id="blabla",
                properties={
                    "xyz": 500,
                    "location": "London",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )

            _create_event(
                team=self.team,
                event="session end",
                distinct_id="blabla",
                properties={
                    "xyz": 500,
                    "location": "Belo Horizonte",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )

            _create_event(
                team=self.team,
                event="session end",
                distinct_id="blabla",
                properties={
                    "xyz": 400,
                    "location": "",
                    "$session_id": s1,
                    "$group_0": "org:5",
                },
            )

    def _run(self, extra: Optional[dict] = None, run_at: Optional[str] = None):
        flush_persons_and_events()
        query_dict = {
            "series": [
                {
                    "event": "session start",
                    "math": "sum",
                    "math_property": "xyz",
                },
                {
                    "event": "session start",
                    "math": "avg",
                    "math_property": "xyz",
                },
            ],
            "trendsFilter": TrendsFilter(formula="A + B"),
        }
        if extra:
            query_dict.update(extra)
        with freeze_time(run_at or "2020-01-04T13:01:01Z"):
            trend_query = TrendsQuery(**query_dict)
            tqr = TrendsQueryRunner(team=self.team, query=trend_query)
            return tqr.calculate().results

    @snapshot_clickhouse_queries
    def test_hour_interval_hour_level_relative(self):
        data = self._run({"dateRange": {"date_from": "-24h"}, "interval": "hour"}, run_at="2020-01-03T13:05:01Z")[0][
            "data"
        ]
        self.assertEqual(
            data,
            [
                1200.0,  # starting at 2020-01-02 13:00 - 24 h before run_at (rounded to start of interval, i.e. hour)
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
                0.0,
                1350.0,
            ],
        )

    @snapshot_clickhouse_queries
    def test_hour_interval_day_level_relative(self):
        data = self._run({"dateRange": {"date_from": "-1d"}, "interval": "hour"}, run_at="2020-01-03T13:05:01Z")[0][
            "data"
        ]
        self.assertEqual(
            data,
            [
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
                0.0,
                0.0,
                1200.0,  # 2020-01-02 13:00 - 24 h before run_at (rounded to start of interval, i.e. hour)
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
                0.0,
                1350.0,
            ],
        )

    def test_day_interval(self):
        data = self._run({"dateRange": {"date_from": "-3d"}}, run_at="2020-01-03T13:05:01Z")[0]["data"]
        self.assertEqual(data, [0.0, 0.0, 1200.0, 1350.0])

    def test_week_interval(self):
        data = self._run({"dateRange": {"date_from": "-2w"}, "interval": "week"}, run_at="2020-01-03T13:05:01Z")[0][
            "data"
        ]
        self.assertEqual(data, [0.0, 0.0, 2160.0])

    def test_month_interval(self):
        data = self._run({"dateRange": {"date_from": "-2m"}, "interval": "month"}, run_at="2020-01-03T13:05:01Z")[0][
            "data"
        ]
        self.assertEqual(data, [0.0, 0.0, 2160.0])

    def test_formula(self):
        self.assertEqual(
            self._run({"trendsFilter": {"formula": "A - B"}})[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 600.0, 450.0, 0.0],
        )
        self.assertEqual(
            self._run({"trendsFilter": {"formula": "A * B"}})[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 270000.0, 405000.0, 0.0],
        )
        self.assertEqual(
            self._run({"trendsFilter": {"formula": "A / B"}})[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 3.0, 2.0, 0.0],
        )
        self.assertEqual(
            self._run({"trendsFilter": {"formula": "(A/3600)/B"}})[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1 / 1200, 1 / 1800, 0.0],
        )
        self.assertEqual(self._run({"trendsFilter": {"formula": "(A/3600)/B"}})[0]["count"], 1 / 720)

        self.assertEqual(
            self._run({"trendsFilter": {"formula": "A/0"}})[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(self._run({"trendsFilter": {"formula": "A/0"}})[0]["count"], 0)

    @snapshot_clickhouse_queries
    def test_formula_with_unique_sessions(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                {
                    "series": [
                        {"event": "session start", "math": "unique_session"},
                        {"event": "session start", "math": "dau"},
                    ],
                    "trendsFilter": {
                        "formula": "A / B",
                    },
                }
            )
            self.assertEqual(action_response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0])

    @snapshot_clickhouse_queries
    def test_regression_formula_with_unique_sessions_2x_and_duration_filter(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                {
                    "series": [
                        {
                            "event": "session start",
                            "math": "unique_session",
                            "properties": [
                                {
                                    "key": "$session_duration",
                                    "value": 12,
                                    "operator": "gt",
                                    "type": "session",
                                }
                            ],
                        },
                        {"event": "session start", "math": "unique_session"},
                    ],
                    "trendsFilter": {
                        "formula": "A / B",
                    },
                }
            )

            self.assertEqual(action_response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0])

    @snapshot_clickhouse_queries
    def test_regression_formula_with_unique_sessions_2x_and_duration_filter_2x(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                {
                    "series": [
                        {
                            "event": "$autocapture",
                            "math": "unique_session",
                            "properties": [
                                {
                                    "key": "$session_duration",
                                    "type": "session",
                                    "value": 30,
                                    "operator": "lt",
                                }
                            ],
                        },
                        {
                            "event": "session start",
                            "math": "unique_session",
                            "properties": [
                                {
                                    "key": "$session_duration",
                                    "type": "session",
                                    "value": 500,
                                    "operator": "gt",
                                }
                            ],
                        },
                    ],
                    "trendsFilter": {
                        "formula": "B",
                    },
                }
            )

            self.assertEqual(action_response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0])

    @snapshot_clickhouse_queries
    def test_regression_formula_with_session_duration_aggregation(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self._run(
                {
                    "series": [
                        {
                            "event": "session start",
                            "name": "$pageview",
                            "math": "avg",
                            "math_property": "$session_duration",
                        },
                        {
                            "event": "session end",
                            "name": "$pageview",
                            "math": "total",
                        },
                    ],
                    "trendsFilter": {
                        "formula": "A / B",
                    },
                }
            )

            self.assertEqual(action_response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 28860.0, 0.0])

    @snapshot_clickhouse_queries
    def test_aggregated_one_without_events(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                {
                    "trendsFilter": {
                        "display": TRENDS_BOLD_NUMBER,
                        "formula": "B + A",
                    },
                    "series": [
                        {
                            "event": "session start",
                            "name": "session start",
                            "math": "sum",
                            "math_property": "xyz",
                        },
                        {
                            "event": "session error",
                            "name": "session error",
                            "math": "sum",
                            "math_property": "session not here",
                        },
                    ],
                }
            )

        self.assertEqual(response[0]["aggregated_value"], 1800)
        self.assertEqual(response[0]["label"], "Formula (B + A)")

    @snapshot_clickhouse_queries
    def test_breakdown(self):
        response = self._run({"trendsFilter": {"formula": "A - B"}, "breakdownFilter": {"breakdown": "location"}})
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 450.0, 0.0])
        self.assertEqual(response[0]["breakdown_value"], "London")
        self.assertEqual(response[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 250.0, 0.0, 0.0])
        self.assertEqual(response[1]["label"], "Formula (A - B)")
        self.assertEqual(response[1]["breakdown_value"], "Paris")

    @snapshot_clickhouse_queries
    def test_breakdown_aggregated(self):
        response = self._run(
            {"trendsFilter": {"formula": "A - B", "display": TRENDS_PIE}, "breakdownFilter": {"breakdown": "location"}}
        )
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["aggregated_value"], 866.6666666666667)
        self.assertEqual(response[0]["label"], "Formula (A - B)")
        self.assertEqual(response[0]["breakdown_value"], "London")
        self.assertEqual(response[1]["aggregated_value"], 250)
        self.assertEqual(response[1]["label"], "Formula (A - B)")
        self.assertEqual(response[1]["breakdown_value"], "Paris")

    @snapshot_clickhouse_queries
    def test_breakdown_with_different_breakdown_values_per_series(self):
        response = self._run(
            {
                "series": [
                    {
                        "event": "session start",
                        "math": "sum",
                        "math_property": "xyz",
                    },
                    {
                        "event": "session end",
                        "math": "sum",
                        "math_property": "xyz",
                    },
                ],
                "trendsFilter": {"formula": "A + B"},
                "breakdownFilter": {"breakdown": "location"},
            }
        )

        self.assertEqual(len(response), 4)

        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 400.0, 1400.0, 0.0])
        self.assertEqual(response[0]["label"], "Formula (A + B)")
        self.assertEqual(response[0]["breakdown_value"], "London")

        self.assertEqual(response[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 500.0, 0.0, 0.0])
        self.assertEqual(response[1]["label"], "Formula (A + B)")
        self.assertEqual(response[1]["breakdown_value"], "Paris")

        # Regression test to ensure we actually get data for "Belo Horizonte" below
        # We previously had a bug where if series B,C,D, etc. had a value not present
        # in series A, we'd just default to an empty string
        self.assertEqual(response[2]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 500.0, 0.0])
        self.assertEqual(response[2]["label"], "Formula (A + B)")
        self.assertEqual(response[2]["breakdown_value"], "Belo Horizonte")

        # empty string values are considered "None"
        self.assertEqual(response[3]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 400.0, 0.0])
        self.assertEqual(response[3]["label"], "Formula (A + B)")
        self.assertEqual(response[3]["breakdown_value"], "$$_posthog_breakdown_null_$$")

    def test_breakdown_counts_of_different_events_one_without_events(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            response = self._run(
                {
                    "trendsFilter": {"display": "ActionsLineGraph", "formula": "B / A"},
                    "breakdownFilter": {
                        "breakdown": "location",
                        "breakdown_type": "event",
                    },
                    "series": [
                        {
                            "event": "session start",
                            "name": "session start",
                        },
                        {
                            "event": "session error",
                            "name": "session error",
                        },
                    ],
                }
            )
        self.assertEqual(
            response,
            [
                {
                    "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "count": 0.0,
                    "labels": [
                        "28-Dec-2019",
                        "29-Dec-2019",
                        "30-Dec-2019",
                        "31-Dec-2019",
                        "1-Jan-2020",
                        "2-Jan-2020",
                        "3-Jan-2020",
                        "4-Jan-2020",
                    ],
                    "days": [
                        "2019-12-28",
                        "2019-12-29",
                        "2019-12-30",
                        "2019-12-31",
                        "2020-01-01",
                        "2020-01-02",
                        "2020-01-03",
                        "2020-01-04",
                    ],
                    "label": "Formula (B / A)",
                    "breakdown_value": "Paris",
                    "action": None,
                    "filter": mock.ANY,
                    "order": 0,
                },
                {
                    "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "count": 0.0,
                    "labels": [
                        "28-Dec-2019",
                        "29-Dec-2019",
                        "30-Dec-2019",
                        "31-Dec-2019",
                        "1-Jan-2020",
                        "2-Jan-2020",
                        "3-Jan-2020",
                        "4-Jan-2020",
                    ],
                    "days": [
                        "2019-12-28",
                        "2019-12-29",
                        "2019-12-30",
                        "2019-12-31",
                        "2020-01-01",
                        "2020-01-02",
                        "2020-01-03",
                        "2020-01-04",
                    ],
                    "label": "Formula (B / A)",
                    "breakdown_value": "London",
                    "action": None,
                    "filter": mock.ANY,
                    "order": 0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_breakdown_cohort(self):
        cohort: Cohort = Cohort.objects.create(
            id=999932324,
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self._run({"breakdownFilter": {"breakdown": ["all", cohort.pk], "breakdown_type": "cohort"}})

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 1350.0, 0.0])
        self.assertEqual(response[0]["breakdown_value"], "all")
        self.assertEqual(response[0]["label"], "Formula (A + B)")
        self.assertEqual(response[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 1350.0, 0.0])
        self.assertEqual(response[1]["label"], "Formula (A + B)")
        self.assertEqual(response[1]["breakdown_value"], cohort.pk)

    @snapshot_clickhouse_queries
    def test_breakdown_hogql(self):
        response = self._run(
            {
                "breakdownFilter": {
                    "breakdown": "concat(person.properties.$some_prop, ' : ', properties.location)",
                    "breakdown_type": "hogql",
                }
            }
        )
        self.assertEqual(
            [series["breakdown_value"] for series in response],
            ["some_val : London", "some_val : Paris"],
        )
        self.assertEqual(
            [
                [0.0, 0.0, 0.0, 0.0, 0.0, 800.0, 1350.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 750.0, 0.0, 0.0],
            ],
            [series["data"] for series in response],
        )

    def test_breakdown_mismatching_sizes(self):
        response = self._run(
            {
                "series": [{"event": "session start"}, {"event": "session end"}],
                "breakdownFilter": {
                    "breakdown": "location",
                },
                "trendsFilter": {"formula": "A + B"},
            }
        )

        self.assertEqual(len(response), 4, response)
        self.assertEqual(response[0]["breakdown_value"], "London")
        self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 1, 3, 0])
        self.assertEqual(response[1]["breakdown_value"], "Paris")
        self.assertEqual(response[1]["data"], [0, 0, 0, 0, 0, 2, 0, 0])
        self.assertEqual(response[2]["breakdown_value"], "Belo Horizonte")
        self.assertEqual(response[2]["data"], [0, 0, 0, 0, 0, 0, 1, 0])
        self.assertEqual(response[3]["breakdown_value"], "$$_posthog_breakdown_null_$$")
        self.assertEqual(response[3]["data"], [0, 0, 0, 0, 0, 0, 1, 0])

    def test_global_properties(self):
        self.assertEqual(
            self._run({"properties": [{"key": "$current_url", "value": "http://example.org"}]})[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 400.0, 0.0, 0.0],
        )

    def test_properties_with_escape_params(self):
        # regression test
        self.assertEqual(
            self._run(
                {
                    "properties": [
                        {
                            "key": "$current_url",
                            "value": "http://localhost:8000/insights?insight=TRENDS&interval=day&display=ActionsLineGraph&actions=%5B%5D&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%2C%7B%22id%22%3A%22%24pageview%2",
                        }
                    ]
                }
            )[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )

    def test_event_properties(self):
        self.assertEqual(
            self._run(
                {
                    "series": [
                        {
                            "event": "session start",
                            "math": "sum",
                            "math_property": "xyz",
                            "properties": [{"key": "$current_url", "value": "http://example.org"}],
                        },
                        {
                            "event": "session start",
                            "math": "avg",
                            "math_property": "xyz",
                        },
                    ]
                }
            )[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 500.0, 450.0, 0.0],
        )

    def test_compare(self):
        response = self._run(
            {
                "dateRange": {
                    "date_from": "-1dStart",
                },
                "compareFilter": {"compare": True},
            }
        )
        self.assertEqual(response[0]["days"], ["2020-01-03", "2020-01-04"])
        self.assertEqual(response[1]["days"], ["2020-01-01", "2020-01-02"])
        self.assertEqual(response[0]["data"], [1350.0, 0.0])
        self.assertEqual(response[1]["data"], [0.0, 1200.0])

    def test_aggregated(self):
        self.assertEqual(
            self._run(
                {
                    "trendsFilter": {
                        "display": TRENDS_PIE,
                        "formula": "A + B",
                    }
                }
            )[0]["aggregated_value"],
            2160.0,
        )

    def test_cumulative(self):
        response = self._run({"trendsFilter": {"display": TRENDS_CUMULATIVE, "formula": "A + B"}})
        self.assertEqual(len(response), 1)
        self.assertEqual(
            response[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 2550.0, 2550.0],
        )
        self.assertEqual(
            response[0]["days"],
            [
                "2019-12-28",
                "2019-12-29",
                "2019-12-30",
                "2019-12-31",
                "2020-01-01",
                "2020-01-02",
                "2020-01-03",
                "2020-01-04",
            ],
        )

    def test_multiple_events(self):
        # regression test
        self.assertEqual(
            self._run(
                {
                    "series": [
                        {
                            "event": "session start",
                            "math": "sum",
                            "math_property": "xyz",
                        },
                        {
                            "event": "session start",
                            "math": "avg",
                            "math_property": "xyz",
                        },
                        {
                            "event": "session start",
                            "math": "avg",
                            "math_property": "xyz",
                        },
                    ]
                }
            )[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 1350.0, 0.0],
        )

    def test_session_formulas(self):
        self.assertEqual(
            self._run(
                {
                    "series": [
                        {"event": "session start", "math": "unique_session"},
                        {"event": "session start", "math": "unique_session"},
                    ]
                }
            )[0]["data"],
            [0, 0, 0, 0, 0, 2, 2, 0],
        )

    def test_group_formulas(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        self.assertEqual(
            self._run(
                {
                    "series": [
                        {
                            "event": "session start",
                            "math": "unique_group",
                            "math_group_type_index": 0,
                        },
                        {
                            "event": "session start",
                            "math": "unique_group",
                            "math_group_type_index": 0,
                        },
                    ]
                }
            )[0]["data"],
            [0, 0, 0, 0, 0, 2, 2, 0],
        )
