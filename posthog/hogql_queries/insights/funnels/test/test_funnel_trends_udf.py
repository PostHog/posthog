import datetime
from typing import cast
from unittest.mock import patch, Mock

from hogql_parser import parse_expr
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR, FunnelOrderType
from posthog.hogql.constants import HogQLGlobalSettings, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.test_funnel_trends import BaseTestFunnelTrends
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.schema import (
    FunnelsQuery,
    FunnelsQueryResponse,
    EventsNode,
    BreakdownFilter,
    FunnelsFilter,
    FunnelVizType,
    BreakdownAttributionType,
    InsightDateRange,
    IntervalType,
)
from posthog.test.base import _create_person, _create_event


@patch(
    "posthoganalytics.feature_enabled",
    new=Mock(side_effect=lambda key, *args, **kwargs: key == "insight-funnels-use-udf-trends"),
)
class TestFunnelTrendsUDF(BaseTestFunnelTrends):
    __test__ = True

    def test_redundant_event_filtering(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "-14d",
            "funnel_viz_type": "trends",
            "interval": "day",
            "events": [
                {"id": "$pageview", "order": 1},
                {"id": "insight viewed", "order": 2},
            ],
        }

        _create_person(
            distinct_ids=["many_other_events"],
            team_id=self.team.pk,
            properties={"test": "okay"},
        )
        now = datetime.datetime.now()
        for i in range(10):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="many_other_events",
                timestamp=now - datetime.timedelta(days=11 + i),
            )

        query = cast(FunnelsQuery, filter_to_query(filters))
        runner = FunnelsQueryRunner(query=query, team=self.team)
        inner_aggregation_query = runner.funnel_class._inner_aggregation_query()
        inner_aggregation_query.select.append(
            parse_expr(f"{runner.funnel_class.udf_event_array_filter()} AS filtered_array")
        )
        inner_aggregation_query.having = None
        response = execute_hogql_query(
            query_type="FunnelsQuery",
            query=inner_aggregation_query,
            team=self.team,
            settings=HogQLGlobalSettings(
                # Make sure funnel queries never OOM
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
                allow_experimental_analyzer=True,
            ),
        )
        # Make sure the events have been condensed down to two
        self.assertEqual(2, len(response.results[0][-1]))

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
            dateRange=InsightDateRange(date_from="2024-01-01", date_to="2024-01-08"),
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
