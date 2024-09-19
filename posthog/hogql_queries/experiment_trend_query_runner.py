from django.conf import settings
from posthog.hogql import ast
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.experiment import Experiment
from posthog.schema import (
    ExperimentTrendQuery,
    ExperimentTrendQueryResponse,
    ExperimentVariantTrendResult,
)
from typing import Any
import threading


class ExperimentTrendQueryRunner(QueryRunner):
    query: ExperimentTrendQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag

        self.query_runner = TrendsQueryRunner(
            query=self.query.count_source, team=self.team, timings=self.timings, limit_context=self.limit_context
        )
        self.exposure_query_runner = TrendsQueryRunner(
            query=self.query.exposure_source, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def calculate(self) -> ExperimentTrendQueryResponse:
        count_response = None
        exposure_response = None
        errors = []

        def run(query_runner: TrendsQueryRunner, is_parallel: bool):
            try:
                return query_runner.calculate()
            except Exception as e:
                errors.append(e)
            finally:
                if is_parallel:
                    from django.db import connection

                    # This will only close the DB connection for the newly spawned thread and not the whole app
                    connection.close()

        # This exists so that we're not spawning threads during unit tests
        if settings.IN_UNIT_TESTING:
            count_response = run(self.query_runner, False)
            exposure_response = run(self.exposure_query_runner, False)
        else:
            jobs = [
                threading.Thread(target=run, args=(self.query_runner, True)),
                threading.Thread(target=run, args=(self.exposure_query_runner, True)),
            ]
            [j.start() for j in jobs]  # type: ignore
            [j.join() for j in jobs]  # type: ignore

            count_response = getattr(jobs[0], "result", None)
            exposure_response = getattr(jobs[1], "result", None)

        # Raise any errors raised in a separate thread
        if len(errors) > 0:
            raise errors[0]

        if count_response is None or exposure_response is None:
            raise ValueError("One or both query runners failed to produce a response")

        results = self._process_results(count_response.results, exposure_response.results)
        return ExperimentTrendQueryResponse(insight="TRENDS", results=results)

    def _process_results(
        self, count_results: list[dict[str, Any]], exposure_results: list[dict[str, Any]]
    ) -> dict[str, ExperimentVariantTrendResult]:
        variants = self.feature_flag.variants
        processed_results = {variant["key"]: ExperimentVariantTrendResult(count=0, exposure=0) for variant in variants}

        for result in count_results:
            variant = result.get("breakdown_value")
            if variant in processed_results:
                processed_results[variant].count += result.get("count", 0)

        for result in exposure_results:
            variant = result.get("breakdown_value")
            if variant in processed_results:
                processed_results[variant].exposure += result.get("count", 0)

        return processed_results

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.count_source.kind} to query")
