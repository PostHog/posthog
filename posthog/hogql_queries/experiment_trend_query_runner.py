from django.conf import settings
from posthog.hogql import ast
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    ExperimentTrendQuery,
    ExperimentTrendQueryResponse,
    ExperimentVariantTrendResult,
)
from typing import Optional, Any
import threading


class ExperimentTrendQueryRunner(QueryRunner):
    query: ExperimentTrendQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_runner = TrendsQueryRunner(
            query=self.query.count_source, team=self.team, timings=self.timings, limit_context=self.limit_context
        )
        self.exposure_query_runner = TrendsQueryRunner(
            query=self.query.exposure_source, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def calculate(self) -> ExperimentTrendQueryResponse:
        res_matrix: list[Optional[Any]] = [None] * 2
        errors = []

        def run(index: int, query_runner: TrendsQueryRunner, is_parallel: bool):
            try:
                response = query_runner.calculate()
                res_matrix[index] = response
            except Exception as e:
                errors.append(e)
            finally:
                if is_parallel:
                    from django.db import connection

                    # This will only close the DB connection for the newly spawned thread and not the whole app
                    connection.close()

        # This exists so that we're not spawning threads during unit tests
        if settings.IN_UNIT_TESTING:
            run(0, self.query_runner, False)
            run(1, self.exposure_query_runner, False)
        else:
            jobs = [
                threading.Thread(target=run, args=(0, self.query_runner, True)),
                threading.Thread(target=run, args=(1, self.exposure_query_runner, True)),
            ]
            [j.start() for j in jobs]  # type:ignore
            [j.join() for j in jobs]  # type:ignore

        # Raise any errors raised in a separate thread
        if len(errors) > 0:
            raise errors[0]

        count_response, exposure_response = res_matrix

        if count_response is None or exposure_response is None:
            raise ValueError("One or both query runners failed to produce a response")

        results = self._process_results(count_response.results, exposure_response.results)
        return ExperimentTrendQueryResponse(insight="TRENDS", results=results)

    def _process_results(
        self, count_results: list[dict[str, Any]], exposure_results: list[dict[str, Any]]
    ) -> dict[str, ExperimentVariantTrendResult]:
        variants = self.query.variants
        processed_results = {variant: ExperimentVariantTrendResult(count=0, exposure=0) for variant in variants}

        for result in count_results:
            variant = result.get("breakdown_value")
            if variant in variants:
                processed_results[variant].count += result.get("count", 0)

        for result in exposure_results:
            variant = result.get("breakdown_value")
            if variant in variants:
                processed_results[variant].exposure += result.get("count", 0)

        return processed_results

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.count_source.kind} to query")
