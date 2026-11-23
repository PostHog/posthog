from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

import orjson
from parameterized import parameterized

from posthog.schema import (
    CachedMarketingAnalyticsAggregatedQueryResponse,
    CachedMarketingAnalyticsTableQueryResponse,
    CachedRetentionQueryResponse,
    CachedTrendsQueryResponse,
    DataWarehouseSyncWarning,
    HogQueryResponse,
    MarketingAnalyticsItem,
    RetentionResult,
)

from posthog.hogql.constants import LimitContext

from posthog.api.services import query as query_service
from posthog.api.services.query import ExecutionMode, RawCachedQueryResponse
from posthog.caching.calculate_results import calculate_for_query_based_insight, plan_query_based_insight
from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import QueryRunner

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.models.dashboard import Dashboard
from products.event_definitions.backend.models import PropertyDefinition
from products.product_analytics.backend.facade.models import Insight


class TestCalculateForQueryBasedInsight(BaseTest):
    def _calculate(self, response, allow_raw_results: bool = False):
        insight = Insight.objects.create(
            team=self.team,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}},
        )
        with patch("posthog.caching.calculate_results.process_query_dict", return_value=response):
            return calculate_for_query_based_insight(
                insight,
                team=self.team,
                execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                user=None,
                allow_raw_results=allow_raw_results,
            )

    # Model-typed results (e.g. retention, paths, marketing analytics) must be dumped to
    # dicts: DRF's JSON encoder falls back to iterating pydantic models, mangling them into
    # (field, value) tuple arrays in the rendered response.
    def test_model_typed_results_are_returned_as_dicts(self):
        response = CachedRetentionQueryResponse(
            results=[RetentionResult(date=datetime(2026, 1, 1, tzinfo=UTC), label="Day 0", values=[])],
            is_cached=True,
            last_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            next_allowed_client_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            cache_key="key",
            timezone="UTC",
        )

        insight_result = self._calculate(response)

        assert isinstance(insight_result.result[0], dict)
        assert insight_result.result[0]["label"] == "Day 0"

    def test_models_nested_in_result_lists_are_returned_as_dicts(self):
        # e.g. CachedMarketingAnalyticsTableQueryResponse.results: list[list[MarketingAnalyticsItem]]
        response = CachedMarketingAnalyticsTableQueryResponse(
            results=[[MarketingAnalyticsItem(key="spend", kind="unit", value=1.0)]],
            is_cached=True,
            last_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            next_allowed_client_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            cache_key="key",
            timezone="UTC",
        )

        insight_result = self._calculate(response)

        assert isinstance(insight_result.result[0][0], dict)
        assert insight_result.result[0][0]["key"] == "spend"

    def test_dict_shaped_results_keep_their_shape_with_models_dumped(self):
        response = CachedMarketingAnalyticsAggregatedQueryResponse(
            results={"spend": MarketingAnalyticsItem(key="spend", kind="unit", value=1.0)},
            is_cached=True,
            last_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            next_allowed_client_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            cache_key="key",
            timezone="UTC",
        )

        insight_result = self._calculate(response)

        assert isinstance(insight_result.result, dict)
        assert isinstance(insight_result.result["spend"], dict)
        assert insight_result.result["spend"]["key"] == "spend"

    def test_scalar_results_pass_through(self):
        insight_result = self._calculate(HogQueryResponse(results="ERROR: nope"))

        assert insight_result.result == "ERROR: nope"

    def test_plain_dict_results_pass_through_without_copying(self):
        series = {"data": [1.0, 2.0], "label": "series", "order": 0}
        response = CachedTrendsQueryResponse(
            results=[series],
            is_cached=True,
            last_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            next_allowed_client_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            cache_key="key",
            timezone="UTC",
        )

        insight_result = self._calculate(response)

        assert insight_result.result[0] is response.results[0]
        assert insight_result.is_cached is True
        assert insight_result.cache_key == "key"

    def test_warehouse_sync_warnings_reach_the_insight_result(self):
        warning = DataWarehouseSyncWarning(
            message="Last sync of `costs` (from DoIt) failed.",
            schema_name="costs",
            source_id="source-1",
            source_type="DoIt",
            status="Failed",
            table_name="doit_costs",
        )
        response = CachedTrendsQueryResponse(
            results=[],
            is_cached=True,
            last_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            next_allowed_client_refresh=datetime(2026, 1, 1, tzinfo=UTC),
            cache_key="key",
            timezone="UTC",
            warnings=[warning],
        )

        insight_result = self._calculate(response)

        assert insight_result.warnings == [warning.model_dump(by_alias=True)]

    def test_raw_cached_results_become_fragments(self):
        raw = orjson.dumps([{"data": [1.0], "label": "series"}])
        response = RawCachedQueryResponse(
            response=CachedTrendsQueryResponse(
                results=[],
                is_cached=True,
                last_refresh=datetime(2026, 1, 1, tzinfo=UTC),
                next_allowed_client_refresh=datetime(2026, 1, 1, tzinfo=UTC),
                cache_key="key",
                timezone="UTC",
            ),
            raw_results=raw,
        )

        insight_result = self._calculate(response, allow_raw_results=True)

        assert isinstance(insight_result.result, orjson.Fragment)
        assert orjson.dumps({"result": insight_result.result}) == b'{"result":[{"data":[1.0],"label":"series"}]}'


_TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}
_SQL_QUERY = {
    "kind": "DataVisualizationNode",
    "source": {"kind": "HogQLQuery", "query": "select count() from events where event = {variables.event_name}"},
}


def _runner_config(runner: QueryRunner) -> dict[str, Any]:
    return {
        "runner": type(runner).__name__,
        "query": runner.query.model_dump(),
        "limit_context": runner.limit_context,
        "is_query_service": runner.is_query_service,
        "serve_raw_cached_results": runner.serve_raw_cached_results,
    }


class TestPlannedQueryMatchesTheQueryRun(BaseTest):
    def _restrict_a_property_for_the_member(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        secret = PropertyDefinition.objects.create(
            team=self.team, name="secret_prop", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=secret,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )

    @parameterized.expand(
        [
            ("trends_tile", _TRENDS_QUERY, False),
            ("trends_tile_restricted_member", _TRENDS_QUERY, True),
            ("sql_tile_with_variables", _SQL_QUERY, False),
            ("sql_tile_with_variables_restricted_member", _SQL_QUERY, True),
        ]
    )
    def test_plans_the_runner_and_cache_key_the_unplanned_path_runs(
        self, _name: str, query: dict, restricted: bool
    ) -> None:
        if restricted:
            self._restrict_a_property_for_the_member()
        dashboard = Dashboard.objects.create(team=self.team, filters={"date_from": "-14d"})
        insight = Insight.objects.create(team=self.team, query=query)
        arguments: dict[str, Any] = {
            "team": self.team,
            "dashboard": dashboard,
            "user": self.user,
            "user_access_control": None,
            "filters_override": {"date_from": "-30d"},
            "variables_override": {"v1": {"code_name": "event_name", "variableId": "v1", "value": "$pageview"}},
            "tile_filters_override": {"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]},
            "allow_raw_results": True,
            "limit_context": LimitContext.QUERY,
        }

        planned = plan_query_based_insight(insight, **arguments)
        run_runners: list[QueryRunner] = []
        run_query_runner = query_service._run_query_runner

        def record_runner(query_runner: QueryRunner, **kwargs: Any) -> Any:
            run_runners.append(query_runner)
            return run_query_runner(query_runner, **kwargs)

        with patch.object(query_service, "_run_query_runner", side_effect=record_runner):
            unplanned = calculate_for_query_based_insight(
                insight, execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE, **arguments
            )

        assert planned is not None
        (run_runner,) = run_runners
        assert _runner_config(planned.query_runner) == _runner_config(run_runner)
        assert planned.cache_key == unplanned.cache_key
        assert ("restricted_properties" in planned.query_runner.get_cache_payload()) is restricted
