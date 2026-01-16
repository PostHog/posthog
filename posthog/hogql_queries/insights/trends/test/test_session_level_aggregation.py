from datetime import datetime

from posthog.test.base import BaseTest

from posthog.schema import ChartDisplayType, EventsNode, PropertyMathType

from posthog.hogql_queries.insights.trends.aggregation_operations import (
    ALLOWED_SESSION_MATH_PROPERTIES,
    AggregationOperations,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team


class TestSessionLevelAggregation(BaseTest):
    def test_aggregating_on_session_property_for_session_duration(self):
        team = Team.objects.create(organization=self.organization)
        series = EventsNode(
            event="$pageview",
            math=PropertyMathType.AVG,
            math_property="$session_duration",
            math_property_type="session_properties",
        )

        query_date_range = QueryDateRange(
            date_range=None,
            team=team,
            interval=None,
            now=datetime.now(),
        )

        agg_ops = AggregationOperations(
            team=team,
            series=series,
            chart_display_type=ChartDisplayType.ACTIONS_LINE_GRAPH,
            query_date_range=query_date_range,
            is_total_value=False,
        )

        assert agg_ops.aggregating_on_session_property() is True
        assert agg_ops.aggregating_on_session_duration() is True

    def test_aggregating_on_session_property_for_bounce_rate(self):
        team = Team.objects.create(organization=self.organization)
        series = EventsNode(
            event="$pageview",
            math=PropertyMathType.AVG,
            math_property="$is_bounce",
            math_property_type="session_properties",
        )

        query_date_range = QueryDateRange(
            date_range=None,
            team=team,
            interval=None,
            now=datetime.now(),
        )

        agg_ops = AggregationOperations(
            team=team,
            series=series,
            chart_display_type=ChartDisplayType.ACTIONS_LINE_GRAPH,
            query_date_range=query_date_range,
            is_total_value=False,
        )

        assert agg_ops.aggregating_on_session_property() is True

    def test_not_aggregating_on_non_session_property(self):
        team = Team.objects.create(organization=self.organization)
        series = EventsNode(
            event="$pageview",
            math=PropertyMathType.AVG,
            math_property="$current_url",
            math_property_type="event_properties",
        )

        query_date_range = QueryDateRange(
            date_range=None,
            team=team,
            interval=None,
            now=datetime.now(),
        )

        agg_ops = AggregationOperations(
            team=team,
            series=series,
            chart_display_type=ChartDisplayType.ACTIONS_LINE_GRAPH,
            query_date_range=query_date_range,
            is_total_value=False,
        )

        assert agg_ops.aggregating_on_session_property() is False

    def test_validate_session_property_success(self):
        team = Team.objects.create(organization=self.organization)

        for property_name in ALLOWED_SESSION_MATH_PROPERTIES:
            series = EventsNode(
                event="$pageview",
                math=PropertyMathType.AVG,
                math_property=property_name,
                math_property_type="session_properties",
            )

            query_date_range = QueryDateRange(
                date_range=None,
                team=team,
                interval=None,
                now=datetime.now(),
            )

            agg_ops = AggregationOperations(
                team=team,
                series=series,
                chart_display_type=ChartDisplayType.ACTIONS_LINE_GRAPH,
                query_date_range=query_date_range,
                is_total_value=False,
            )

            validated = agg_ops._validate_session_property()
            assert validated == property_name

    def test_validate_session_property_failure(self):
        team = Team.objects.create(organization=self.organization)
        series = EventsNode(
            event="$pageview",
            math=PropertyMathType.AVG,
            math_property="$invalid_property",
            math_property_type="session_properties",
        )

        query_date_range = QueryDateRange(
            date_range=None,
            team=team,
            interval=None,
            now=datetime.now(),
        )

        agg_ops = AggregationOperations(
            team=team,
            series=series,
            chart_display_type=ChartDisplayType.ACTIONS_LINE_GRAPH,
            query_date_range=query_date_range,
            is_total_value=False,
        )

        with self.assertRaises(ValueError) as context:
            agg_ops._validate_session_property()

        assert "Invalid session property" in str(context.exception)
