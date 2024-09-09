from posthog.hogql import ast
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.schema import (
    ExperimentResultFunnelQueryResponse,
    ExperimentResultQuery,
    ExperimentResultTrendQueryResponse,
    ExperimentVariantTrendResult,
    ExperimentVariantFunnelResult,
    TrendsQuery,
    FunnelsQuery,
)
from typing import Any, Union

from posthog.models.filters.mixins.utils import cached_property


class ExperimentResultQueryRunner(QueryRunner):
    query: ExperimentResultQuery

    @cached_property
    def source_runner(self) -> QueryRunner:
        return get_query_runner(self.query.source, self.team, self.timings, self.limit_context)

    def calculate(self) -> Union[ExperimentResultTrendQueryResponse, ExperimentResultFunnelQueryResponse]:
        source_query = self.query.source
        if isinstance(source_query, TrendsQuery):
            return self._calculate_trends()
        elif isinstance(source_query, FunnelsQuery):
            return self._calculate_funnels()
        else:
            raise ValueError(f"Unsupported query type: {type(source_query)}")

    def _calculate_trends(self) -> ExperimentResultTrendQueryResponse:
        trends_response = self.source_runner.calculate()
        results = self._process_trends_results(trends_response.results)
        return ExperimentResultTrendQueryResponse(insight="TRENDS", results=results)

    def _calculate_funnels(self) -> ExperimentResultFunnelQueryResponse:
        funnels_response = self.source_runner.calculate()
        results = self._process_funnels_results(funnels_response.results)
        return ExperimentResultFunnelQueryResponse(insight="FUNNELS", results=results)

    def _process_trends_results(self, trends_results: list[dict[str, Any]]) -> dict[str, ExperimentVariantTrendResult]:
        variants = self.query.variants
        processed_results = {variant: ExperimentVariantTrendResult(count=0) for variant in variants}

        for result in trends_results:
            variant = result.get("breakdown_value")
            if variant in variants:
                processed_results[variant].count += result.get("count", 0)

        return processed_results

    def _process_funnels_results(
        self, funnels_results: list[list[dict[str, Any]]]
    ) -> dict[str, ExperimentVariantFunnelResult]:
        variants = self.query.variants
        processed_results = {
            variant: ExperimentVariantFunnelResult(success_count=0, failure_count=0) for variant in variants
        }

        for result in funnels_results:
            first_step = result[0]
            last_step = result[-1]
            variant = first_step.get("breakdown_value")
            variant_str = variant[0] if isinstance(variant, list) else str(variant)
            if variant_str in variants:
                total_count = first_step.get("count", 0)
                success_count = last_step.get("count", 0) if len(result) > 1 else 0
                processed_results[variant_str].success_count = success_count
                processed_results[variant_str].failure_count = total_count - success_count

        return processed_results

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to query")
