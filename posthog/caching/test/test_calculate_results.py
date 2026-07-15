from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import (
    CachedMarketingAnalyticsAggregatedQueryResponse,
    CachedMarketingAnalyticsTableQueryResponse,
    CachedRetentionQueryResponse,
    CachedTrendsQueryResponse,
    HogQueryResponse,
    MarketingAnalyticsItem,
    RetentionResult,
)

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight

from products.product_analytics.backend.models.insight import Insight


class TestCalculateForQueryBasedInsight(BaseTest):
    def _calculate(self, response):
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
        series = {"data": [1.0, 2.0], "label": "series", "action": {"order": 0}}
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
