from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import (
    ActorsQuery,
    DashboardFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationResultsType,
    FunnelsActorsQuery,
    FunnelsQuery,
    InsightActorsQuery,
    PropertyGroupFilter,
    PropertyOperator,
    TrendsQuery,
)

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.apply_dashboard_filters import apply_dashboard_filters_to_dict
from posthog.hogql_queries.insights.insight_actors_query_runner import InsightActorsQueryRunner


class TestInsightActorsQueryDashboardFilters(BaseTest):
    """Regression tests for the persons-modal subscription bug where dashboard filters were
    silently dropped from FunnelsActorsQuery / InsightActorsQuery / FunnelCorrelationActorsQuery
    insights because the InsightActorsQueryRunner had no apply_dashboard_filters override and
    the wrapping actors-query nodes do not carry properties / dateRange themselves."""

    def _funnels_actors_query(self) -> FunnelsActorsQuery:
        return FunnelsActorsQuery(
            funnelStep=2,
            source=FunnelsQuery(
                dateRange=DateRange(date_from="-7d"),
                series=[EventsNode(event="$pageview"), EventsNode(event="$pageview")],
            ),
        )

    def _insight_actors_query(self) -> InsightActorsQuery:
        return InsightActorsQuery(
            day="2024-01-01",
            source=TrendsQuery(
                dateRange=DateRange(date_from="-7d"),
                series=[EventsNode(event="$pageview")],
            ),
        )

    def _funnel_correlation_actors_query(self) -> FunnelCorrelationActorsQuery:
        return FunnelCorrelationActorsQuery(
            source=FunnelCorrelationQuery(
                funnelCorrelationType=FunnelCorrelationResultsType.EVENTS,
                source=FunnelsActorsQuery(
                    source=FunnelsQuery(
                        dateRange=DateRange(date_from="-7d"),
                        series=[EventsNode(event="$pageview"), EventsNode(event="$pageview")],
                    ),
                ),
            ),
        )

    def test_funnels_actors_query_applies_dashboard_filters_to_inner_funnels_query(self):
        query = self._funnels_actors_query()
        runner = InsightActorsQueryRunner(query=query, team=self.team)

        runner.apply_dashboard_filters(
            DashboardFilter(
                date_from="2024-07-07",
                date_to="2024-07-14",
                properties=[EventPropertyFilter(key="key", value="value", operator=PropertyOperator.EXACT)],
            )
        )

        funnels_query = cast(FunnelsQuery, runner.query.source)
        assert funnels_query.dateRange is not None
        assert funnels_query.dateRange.date_from == "2024-07-07"
        assert funnels_query.dateRange.date_to == "2024-07-14"
        assert funnels_query.properties == [
            EventPropertyFilter(key="key", value="value", operator=PropertyOperator.EXACT)
        ]

    def test_insight_actors_query_applies_dashboard_filters_to_inner_trends_query(self):
        query = self._insight_actors_query()
        runner = InsightActorsQueryRunner(query=query, team=self.team)

        runner.apply_dashboard_filters(
            DashboardFilter(
                date_from="2024-07-07",
                date_to="2024-07-14",
                properties=[EventPropertyFilter(key="key", value="value", operator=PropertyOperator.EXACT)],
            )
        )

        trends_query = cast(TrendsQuery, runner.query.source)
        assert trends_query.dateRange is not None
        assert trends_query.dateRange.date_from == "2024-07-07"
        assert trends_query.dateRange.date_to == "2024-07-14"
        assert trends_query.properties == [
            EventPropertyFilter(key="key", value="value", operator=PropertyOperator.EXACT)
        ]

    def test_funnel_correlation_actors_query_descends_through_three_layers(self):
        query = self._funnel_correlation_actors_query()
        runner = InsightActorsQueryRunner(query=query, team=self.team)

        runner.apply_dashboard_filters(
            DashboardFilter(
                date_from="2024-07-07",
                date_to="2024-07-14",
                properties=[EventPropertyFilter(key="key", value="value", operator=PropertyOperator.EXACT)],
            )
        )

        # FunnelCorrelationActorsQuery -> FunnelCorrelationQuery -> FunnelsActorsQuery -> FunnelsQuery
        funnels_query = cast(FunnelsQuery, runner.query.source.source.source)
        assert funnels_query.dateRange is not None
        assert funnels_query.dateRange.date_from == "2024-07-07"
        assert funnels_query.dateRange.date_to == "2024-07-14"
        assert funnels_query.properties == [
            EventPropertyFilter(key="key", value="value", operator=PropertyOperator.EXACT)
        ]

    def test_apply_dashboard_filters_does_not_capture_not_implemented_exception(self):
        # capture_exception is the swallow point that hid this bug in production - the base
        # apply_dashboard_filters bails out and silently captures `NotImplementedError`. If the
        # override regresses we'd start capturing again, so guard against that explicitly.
        query = self._funnels_actors_query()
        runner = InsightActorsQueryRunner(query=query, team=self.team)

        with patch("posthog.hogql_queries.query_runner.capture_exception") as captured:
            runner.apply_dashboard_filters(DashboardFilter(date_from="2024-07-07"))

        captured.assert_not_called()

    def test_actors_query_runner_propagates_filters_into_inner_funnels_query(self):
        # End-to-end check that goes through ActorsQueryRunner -> InsightActorsQueryRunner -> FunnelsQueryRunner.
        funnels_actors = self._funnels_actors_query()
        actors = ActorsQuery(source=funnels_actors)
        runner = ActorsQueryRunner(query=actors, team=self.team)

        runner.apply_dashboard_filters(
            DashboardFilter(
                date_from="2024-07-07",
                date_to="2024-07-14",
            )
        )

        funnels_query = cast(FunnelsQuery, runner.query.source.source)
        assert funnels_query.dateRange is not None
        assert funnels_query.dateRange.date_from == "2024-07-07"
        assert funnels_query.dateRange.date_to == "2024-07-14"

    def test_apply_dashboard_filters_to_dict_path_includes_filters_in_inner_query(self):
        # This is the apply_dashboard_filters_to_dict subscription delivery path
        # (calculate_results.py / apply_dashboard_filters.py).
        funnels_actors = self._funnels_actors_query()
        query_dict = funnels_actors.model_dump()
        filters_dict = {
            "date_from": "2024-07-07",
            "date_to": "2024-07-14",
            "properties": [{"key": "key", "value": "value", "operator": "exact", "type": "event"}],
        }

        result = apply_dashboard_filters_to_dict(query_dict, filters_dict, self.team)

        inner = result["source"]
        assert inner["dateRange"]["date_from"] == "2024-07-07"
        assert inner["dateRange"]["date_to"] == "2024-07-14"
        assert inner["properties"] == [{"key": "key", "value": "value", "operator": "exact", "type": "event"}]

    def test_apply_dashboard_filters_existing_query_properties_are_combined(self):
        # When the underlying funnels query already has properties, dashboard filters should be
        # combined into a PropertyGroupFilter rather than replacing the existing ones.
        query = FunnelsActorsQuery(
            source=FunnelsQuery(
                dateRange=DateRange(date_from="-7d"),
                series=[EventsNode(event="$pageview"), EventsNode(event="$pageview")],
                properties=[EventPropertyFilter(key="existing", value="x", operator=PropertyOperator.EXACT)],
            ),
        )
        runner = InsightActorsQueryRunner(query=query, team=self.team)

        runner.apply_dashboard_filters(
            DashboardFilter(
                properties=[EventPropertyFilter(key="dash", value="y", operator=PropertyOperator.EXACT)],
            )
        )

        funnels_query = cast(FunnelsQuery, runner.query.source)
        assert isinstance(funnels_query.properties, PropertyGroupFilter)
