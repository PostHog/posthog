from zoneinfo import ZoneInfo
from django.conf import settings
from posthog.hogql import ast
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.experiment import Experiment
from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS
from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    EventPropertyFilter,
    EventsNode,
    ExperimentTrendQuery,
    ExperimentTrendQueryResponse,
    ExperimentVariantTrendResult,
    InsightDateRange,
    TrendsFilter,
    TrendsQuery,
)
from typing import Any, Optional
import threading


class ExperimentTrendQueryRunner(QueryRunner):
    query: ExperimentTrendQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.breakdown_key = f"$feature/{self.feature_flag.key}"

        self.prepared_count_query = self._prepare_count_query()
        self.prepared_exposure_query = self._prepare_exposure_query()

        self.count_query_runner = TrendsQueryRunner(
            query=self.prepared_count_query, team=self.team, timings=self.timings, limit_context=self.limit_context
        )
        self.exposure_query_runner = TrendsQueryRunner(
            query=self.prepared_exposure_query, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def _uses_math_aggregation_by_user_or_property_value(self, query: TrendsQuery):
        math_keys = ALL_SUPPORTED_MATH_FUNCTIONS
        # "sum" doesn't need special handling, we *can* have custom exposure for sum filters
        if "sum" in math_keys:
            math_keys.remove("sum")
        return any(entity.math in math_keys for entity in query.series)

    def _get_insight_date_range(self) -> InsightDateRange:
        """
        Returns an InsightDateRange object based on the experiment's start and end dates,
        adjusted for the team's timezone if applicable.
        """
        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        return InsightDateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

    def _get_breakdown_filter(self) -> BreakdownFilter:
        return BreakdownFilter(
            breakdown=self.breakdown_key,
            breakdown_type="event",
        )

    def _prepare_count_query(self) -> TrendsQuery:
        """
        This method takes the raw trend query and adapts it
        for the needs of experiment analysis:

        1. Set the trend display type based on whether math aggregation is used
        2. Set the date range to match the experiment's duration, using the project's timezone.
        3. Configure the breakdown to use the feature flag key, which allows us
           to separate results for different experiment variants.
        """
        prepared_count_query = TrendsQuery(**self.query.count_query.model_dump())

        uses_math_aggregation = self._uses_math_aggregation_by_user_or_property_value(prepared_count_query)
        if uses_math_aggregation:
            raise ValueError("Math aggregation is not supported yet")
        else:
            prepared_count_query.trendsFilter = TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)

        prepared_count_query.dateRange = self._get_insight_date_range()
        prepared_count_query.breakdownFilter = self._get_breakdown_filter()
        prepared_count_query.properties = [
            EventPropertyFilter(
                key=self.breakdown_key,
                value=[variant["key"] for variant in self.feature_flag.variants],
                operator="exact",
                type="event",
            )
        ]

        return prepared_count_query

    def _prepare_exposure_query(self) -> TrendsQuery:
        """
        This method prepares the exposure query for the experiment analysis.

        Exposure is the count of users who have seen the experiment. This is necessary to calculate the statistical
        significance of the experiment.

        There are 3 possible cases for the exposure query:
        1. If math aggregation is used, we construct an implicit exposure query
        2. Otherwise, if an exposure query is provided, we use it as is, adapting it to the experiment's duration and breakdown
        3. Otherwise, we construct a default exposure query (the count of $feature_flag_called events)
        """

        # 1. If math aggregation is used, we construct an implicit exposure query
        uses_math_aggregation = self._uses_math_aggregation_by_user_or_property_value(self.query.count_query)
        if uses_math_aggregation:
            raise ValueError("Math aggregation is not supported yet")

        # 2. Otherwise, if an exposure query is provided, we use it as is, just adapting the date range and breakdown
        if self.query.exposure_query:
            prepared_exposure_query = TrendsQuery(**self.query.exposure_query.model_dump())
            prepared_exposure_query.dateRange = self._get_insight_date_range()
            prepared_exposure_query.breakdownFilter = self._get_breakdown_filter()
            prepared_exposure_query.properties = [
                EventPropertyFilter(
                    key=self.breakdown_key,
                    value=[variant["key"] for variant in self.feature_flag.variants],
                    operator="exact",
                    type="event",
                )
            ]
        else:
            # 3. Otherwise, we construct a default exposure query
            prepared_exposure_query = TrendsQuery(
                dateRange=self._get_insight_date_range(),
                series=[
                    EventsNode(
                        event="$feature_flag_called",
                        math="dau",  # TODO sync with frontend!!!
                    )
                ],
                breakdownFilter=self._get_breakdown_filter(),
                properties=[
                    EventPropertyFilter(
                        key=self.breakdown_key,
                        value=[variant["key"] for variant in self.feature_flag.variants],
                        operator="exact",
                        type="event",
                    ),
                    EventPropertyFilter(
                        key="$feature_flag",
                        value=[self.feature_flag.key],
                        operator="exact",
                        type="event",
                    ),
                ],
            )

        return prepared_exposure_query

    def calculate(self) -> ExperimentTrendQueryResponse:
        shared_results: dict[str, Optional[Any]] = {"count_response": None, "exposure_response": None}
        errors = []

        def run(query_runner: TrendsQueryRunner, result_key: str, is_parallel: bool):
            try:
                result = query_runner.calculate()
                shared_results[result_key] = result
            except Exception as e:
                errors.append(e)
            finally:
                if is_parallel:
                    from django.db import connection

                    # This will only close the DB connection for the newly spawned thread and not the whole app
                    connection.close()

        # This exists so that we're not spawning threads during unit tests
        if settings.IN_UNIT_TESTING:
            run(self.count_query_runner, "count_response", False)
            run(self.exposure_query_runner, "exposure_response", False)
        else:
            jobs = [
                threading.Thread(target=run, args=(self.count_query_runner, "count_response", True)),
                threading.Thread(target=run, args=(self.exposure_query_runner, "exposure_response", True)),
            ]
            [j.start() for j in jobs]  # type: ignore
            [j.join() for j in jobs]  # type: ignore

        # Raise any errors raised in a separate thread
        if errors:
            raise errors[0]

        count_response = shared_results["count_response"]
        exposure_response = shared_results["exposure_response"]

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
        raise ValueError(f"Cannot convert source query of type {self.query.count_query.kind} to query")
