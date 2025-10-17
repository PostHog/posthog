import datetime
from typing import cast

from posthog.test.base import _create_event, _create_person
from unittest.mock import Mock, patch

from posthog.schema import (
    BreakdownAttributionType,
    BreakdownFilter,
    DateRange,
    EventsNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelsQueryResponse,
    FunnelVizType,
    IntervalType,
)

from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR, FunnelOrderType
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.test_funnel_trends import BaseTestFunnelTrends
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.test.test_journeys import journeys_for


@patch(
    "posthoganalytics.feature_enabled",
    new=Mock(side_effect=lambda key, *args, **kwargs: key == "insight-funnels-use-udf-trends"),
)
class TestFunnelTrendsUDF(BaseTestFunnelTrends):
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

        self.assertTrue(results.isUdf)

    def test_assert_steps_flag_is_off(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
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

    def test_different_prop_val_in_strict_filter(self):
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="first"), EventsNode(event="second")],
            breakdownFilter=BreakdownFilter(breakdown="bd"),
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-08"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(funnelOrderType=FunnelOrderType.STRICT, funnelVizType=FunnelVizType.TRENDS),
        )

        _create_person(
            distinct_ids=["many_other_events"],
            team_id=self.team.pk,
            properties={"test": "okay"},
        )
        _create_event(
            team=self.team,
            event="first",
            distinct_id="many_other_events",
            properties={"bd": "one"},
            timestamp=datetime.datetime(2024, 1, 2),
        )
        _create_event(
            team=self.team,
            event="first",
            distinct_id="many_other_events",
            properties={"bd": "two"},
            timestamp=datetime.datetime(2024, 1, 3),
        )
        _create_event(
            team=self.team,
            event="unmatched",
            distinct_id="many_other_events",
            properties={"bd": "one"},
            timestamp=datetime.datetime(2024, 1, 4),
        )
        _create_event(
            team=self.team,
            event="unmatched",
            distinct_id="many_other_events",
            properties={"bd": "two"},
            timestamp=datetime.datetime(2024, 1, 5),
        )
        _create_event(
            team=self.team,
            event="second",
            distinct_id="many_other_events",
            properties={"bd": "one"},
            timestamp=datetime.datetime(2024, 1, 6),
        )
        _create_event(
            team=self.team,
            event="second",
            distinct_id="many_other_events",
            properties={"bd": "two"},
            timestamp=datetime.datetime(2024, 1, 7),
        )

        # First Touchpoint (just "one")
        results = FunnelsQueryRunner(query=funnels_query, team=self.team).calculate().results

        self.assertEqual(
            [
                {
                    "breakdown_value": ["one"],
                    "count": 8,
                    "data": [
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ],
                    "days": [
                        "2024-01-01",
                        "2024-01-02",
                        "2024-01-03",
                        "2024-01-04",
                        "2024-01-05",
                        "2024-01-06",
                        "2024-01-07",
                        "2024-01-08",
                    ],
                    "labels": [
                        "1-Jan-2024",
                        "2-Jan-2024",
                        "3-Jan-2024",
                        "4-Jan-2024",
                        "5-Jan-2024",
                        "6-Jan-2024",
                        "7-Jan-2024",
                        "8-Jan-2024",
                    ],
                }
            ],
            results,
        )

        # All events attribution
        assert funnels_query.funnelsFilter is not None
        funnels_query.funnelsFilter.breakdownAttributionType = BreakdownAttributionType.ALL_EVENTS
        results = FunnelsQueryRunner(query=funnels_query, team=self.team).calculate().results

        assert len(results) == 2
        assert all(data == 0 for result in results for data in result["data"])

    # This is a change in behavior that only applies to UDFs - it seems more correct than what was happening before
    # In old style UDFs, an exclusion like this would still count, even if it were outside of the match window
    def test_excluded_after_time_expires(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime.datetime(2021, 5, 1, 0, 0, 0),
            },
            # Exclusion happens after time expires
            {
                "event": "exclusion",
                "timestamp": datetime.datetime(2021, 5, 1, 0, 0, 11),
            },
            {
                "event": "step two",
                "timestamp": datetime.datetime(2021, 5, 1, 0, 0, 12),
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
        self.assertEqual(0, results[0]["reached_to_step_count"])
