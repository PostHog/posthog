from typing import Dict, Optional

from freezegun.api import freeze_time

from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from posthog.constants import TRENDS_CUMULATIVE, TRENDS_PIE
from posthog.models import Cohort, Person
from posthog.models.filters.filter import Filter
from posthog.test.base import APIBaseTest, _create_event


class TestFormula(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()

        Person.objects.create(
            team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
        )
        with freeze_time("2020-01-02T13:01:01Z"):
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={"session duration": 200, "location": "Paris", "$current_url": "http://example.org"},
            )
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={"session duration": 300, "location": "Paris"},
            )
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={"session duration": 400, "location": "London"},
            )
        with freeze_time("2020-01-03T13:01:01Z"):
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={"session duration": 400, "location": "London"},
            )
        with freeze_time("2020-01-03T13:04:01Z"):
            _create_event(
                team=self.team,
                event="session start",
                distinct_id="blabla",
                properties={"session duration": 500, "location": "London"},
            )
            _create_event(
                team=self.team,
                event="session end",
                distinct_id="blabla",
                properties={"session duration": 500, "location": "London"},
            )

    def _run(self, extra: Dict = {}, run_at: Optional[str] = None):
        with freeze_time(run_at or "2020-01-04T13:01:01Z"):
            action_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "events": [
                            {"id": "session start", "math": "sum", "math_property": "session duration"},
                            {"id": "session start", "math": "avg", "math_property": "session duration"},
                        ],
                        "formula": "A + B",
                        **extra,
                    }
                ),
                self.team,
            )
        return action_response

    def test_hour_interval(self):
        data = self._run({"date_from": "-1d", "interval": "hour"}, run_at="2020-01-03T13:05:01Z")[0]["data"]
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
                1200.0,
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
        data = self._run({"date_from": "-3d"}, run_at="2020-01-03T13:05:01Z")[0]["data"]
        self.assertEqual(data, [0.0, 0.0, 1200.0, 1350.0])

    def test_week_interval(self):
        data = self._run({"date_from": "-2w", "interval": "week"}, run_at="2020-01-03T13:05:01Z")[0]["data"]
        self.assertEqual(data, [0.0, 0.0, 2160.0])

    def test_month_interval(self):
        data = self._run({"date_from": "-2m", "interval": "month"}, run_at="2020-01-03T13:05:01Z")[0]["data"]
        self.assertEqual(data, [0.0, 0.0, 2160.0])

    def test_formula(self):
        self.assertEqual(self._run({"formula": "A - B"})[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 600.0, 450.0, 0.0])
        self.assertEqual(self._run({"formula": "A * B"})[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 270000.0, 405000.0, 0.0])
        self.assertEqual(self._run({"formula": "A / B"})[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 3.0, 2.0, 0.0])
        self.assertEqual(self._run({"formula": "(A/3600)/B"})[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(self._run({"formula": "(A/3600)/B"})[0]["count"], 0)

        self.assertEqual(self._run({"formula": "A/0"})[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(self._run({"formula": "A/0"})[0]["count"], 0)

    def test_breakdown(self):
        response = self._run({"formula": "A - B", "breakdown": "location"})
        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 450.0, 0.0])
        self.assertEqual(response[0]["label"], "London")
        self.assertEqual(response[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 250.0, 0.0, 0.0])
        self.assertEqual(response[1]["label"], "Paris")

    def test_breakdown_counts_of_different_events_one_without_events(self):
        with freeze_time("2020-01-04T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "insight": "TRENDS",
                        "display": "ActionsLineGraph",
                        "formula": "B / A",
                        "breakdown": "location",
                        "breakdown_type": "event",
                        "events": [
                            {"id": "session start", "name": "session start", "type": "events", "order": 0},
                            {"id": "session error", "name": "session error", "type": "events", "order": 1},
                        ],
                    }
                ),
                self.team,
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
                    "label": "London",
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
                    "label": "Paris",
                },
            ],
        )

    def test_breakdown_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
        )
        response = self._run({"breakdown": ["all", cohort.pk], "breakdown_type": "cohort"})
        self.assertEqual(response[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 1350.0, 0.0])
        self.assertEqual(response[0]["label"], "all users")
        self.assertEqual(response[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 1350.0, 0.0])
        self.assertEqual(response[1]["label"], "cohort1")

    def test_breakdown_mismatching_sizes(self):
        response = self._run(
            {"events": [{"id": "session start"}, {"id": "session end"},], "breakdown": "location", "formula": "A + B",}
        )

        self.assertEqual(response[0]["label"], "London")
        self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 1, 3, 0])
        self.assertEqual(response[1]["label"], "Paris")
        self.assertEqual(response[1]["data"], [0, 0, 0, 0, 0, 2, 0, 0])

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
                    "events": [
                        {
                            "id": "session start",
                            "math": "sum",
                            "math_property": "session duration",
                            "properties": [{"key": "$current_url", "value": "http://example.org"}],
                        },
                        {"id": "session start", "math": "avg", "math_property": "session duration"},
                    ]
                }
            )[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 500.0, 450.0, 0.0],
        )

    def test_compare(self):
        response = self._run({"date_from": "-1dStart", "compare": True})
        self.assertEqual(response[0]["data"], [1350.0, 0.0])
        self.assertEqual(response[1]["data"], [0, 1200.0, 1350.0])

    def test_pie(self):
        self.assertEqual(self._run({"display": TRENDS_PIE})[0]["aggregated_value"], 2160.0)

    def test_cumulative(self):
        self.assertEqual(
            self._run({"display": TRENDS_CUMULATIVE})[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 2550.0, 2550.0]
        )

    def test_multiple_events(self):
        # regression test
        self.assertEqual(
            self._run(
                {
                    "events": [
                        {"id": "session start", "math": "sum", "math_property": "session duration"},
                        {"id": "session start", "math": "avg", "math_property": "session duration"},
                        {"id": "session start", "math": "avg", "math_property": "session duration"},
                    ]
                }
            )[0]["data"],
            [0.0, 0.0, 0.0, 0.0, 0.0, 1200.0, 1350.0, 0.0],
        )
