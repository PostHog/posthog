from posthog.hogql import ast
from posthog.hogql_queries.query_runner import QueryRunner
from .insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.schema import (
    ExperimentFunnelQuery,
    ExperimentFunnelQueryResponse,
    ExperimentVariantFunnelResult,
)
from typing import Any


class ExperimentFunnelQueryRunner(QueryRunner):
    query: ExperimentFunnelQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_runner = FunnelsQueryRunner(
            query=self.query.source, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def calculate(self) -> ExperimentFunnelQueryResponse:
        response = self.query_runner.calculate()
        results = self._process_results(response.results)
        return ExperimentFunnelQueryResponse(insight="FUNNELS", results=results)

    def _process_results(self, funnels_results: list[list[dict[str, Any]]]) -> dict[str, ExperimentVariantFunnelResult]:
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
