from typing import cast
from unittest.mock import Mock, patch

from freezegun import freeze_time

from hogql_parser import parse_expr
from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql.constants import HogQLGlobalSettings, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.test_funnel_strict import (
    BaseTestFunnelStrictStepsBreakdown,
    BaseTestFunnelStrictSteps,
    BaseTestStrictFunnelGroupBreakdown,
    BaseTestFunnelStrictStepsConversionTime,
)
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.schema import FunnelsQuery
from posthog.test.base import _create_person, _create_event


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsBreakdownUDF(BaseTestFunnelStrictStepsBreakdown):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsUDF(BaseTestFunnelStrictSteps):
    __test__ = True

    def test_redundant_event_filtering_strict_funnel(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
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
        for _ in range(10):
            _create_event(team=self.team, event="user signed up", distinct_id="many_other_events")

        query = cast(FunnelsQuery, filter_to_query(filters))
        runner = FunnelsQueryRunner(query=query, team=self.team)
        inner_aggregation_query = runner.funnel_class._inner_aggregation_query()
        inner_aggregation_query.select.append(parse_expr(f"{runner.funnel_class._array_filter()} AS filtered_array"))
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
        # Make sure the events have been condensed down to one
        self.assertEqual(1, len(response.results[0][-1]))

    def test_multiple_events_same_timestamp_doesnt_blow_up(self):
        _create_person(distinct_ids=["test"], team_id=self.team.pk)
        with freeze_time("2024-01-10T12:01:00"):
            for _ in range(30):
                _create_event(team=self.team, event="step one", distinct_id="test")
            _create_event(team=self.team, event="step two", distinct_id="test")
            _create_event(team=self.team, event="step three", distinct_id="test")
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "date_from": "2024-01-10 00:00:00",
            "date_to": "2024-01-12 00:00:00",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        self.assertEqual(1, results[-1]["count"])


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestStrictFunnelGroupBreakdownUDF(BaseTestStrictFunnelGroupBreakdown):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsConversionTimeUDF(BaseTestFunnelStrictStepsConversionTime):
    __test__ = True
