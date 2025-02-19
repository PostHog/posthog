from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.schema import (
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ExperimentExposureTimeSeries,
    DateRange,
    IntervalType,
    CachedExperimentExposureQueryResponse,
)


class ExperimentExposuresQueryRunner(QueryRunner):
    query: ExperimentExposureQuery
    response: ExperimentExposureQueryResponse
    cached_response: CachedExperimentExposureQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.date_range = self._get_date_range()

    def _get_date_range(self) -> DateRange:
        """
        Returns a DateRange object based on the experiment's start and end dates,
        adjusted for the team's timezone if applicable.
        """
        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        return DateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

    def _get_exposure_query(self) -> ast.SelectQuery:
        feature_flag_key = self.feature_flag.key

        test_accounts_filter: list[ast.Expr] = []
        if isinstance(self.team.test_account_filters, list) and len(self.team.test_account_filters) > 0:
            for property in self.team.test_account_filters:
                test_accounts_filter.append(property_to_expr(property, self.team))

        date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

        exposure_query = ast.SelectQuery(
            select=[
                parse_expr("toDate(timestamp) as day"),
                parse_expr("replaceAll(JSONExtractRaw(properties, '$feature_flag_response'), '\"', '') AS variant"),
                parse_expr("count(DISTINCT distinct_id) as exposed_count"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.And(
                        exprs=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["event"]),
                                right=ast.Constant(value="$feature_flag_called"),
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=parse_expr("replaceAll(JSONExtractRaw(properties, '$feature_flag'), '\"', '')"),
                                right=ast.Constant(value=feature_flag_key),
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.In,
                                left=parse_expr(
                                    "replaceAll(JSONExtractRaw(properties, '$feature_flag_response'), '\"', '')"
                                ),
                                right=ast.Constant(value=self.variants),
                            ),
                        ]
                    ),
                    # Filter by experiment date range
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=date_range_query.date_from()),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=date_range_query.date_to()),
                    ),
                    *test_accounts_filter,
                ]
            ),
            group_by=[ast.Field(chain=["day"]), ast.Field(chain=["variant"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["day"]), order="ASC")],
        )

        return exposure_query

    def calculate(self) -> ExperimentExposureQueryResponse:
        response = execute_hogql_query(
            query=self._get_exposure_query(),
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        response.results = self._fill_date_gaps(response.results)
        variant_series: dict[str, ExperimentExposureTimeSeries] = {}

        # Organize results by variant
        variant_data: dict[str, dict[str, int]] = {}
        for result in response.results:
            day, variant, count = result
            if variant not in variant_data:
                variant_data[variant] = {}
            variant_data[variant][day.isoformat()] = count

        # Create cumulative series for each variant
        for variant, daily_counts in variant_data.items():
            sorted_days = sorted(daily_counts.keys())
            cumulative_counts = []
            running_total = 0

            for day in sorted_days:
                running_total += daily_counts[day]
                cumulative_counts.append(int(running_total))

            variant_series[variant] = ExperimentExposureTimeSeries(
                variant=variant, days=sorted_days, exposure_counts=cumulative_counts
            )

        return ExperimentExposureQueryResponse(
            timeseries=list(variant_series.values()),
            total_exposures={variant: int(series.exposure_counts[-1]) for variant, series in variant_series.items()},
            date_range=self.date_range,
        )

    def to_query(self) -> ast.SelectQuery:
        raise ValueError("Cannot convert exposure query to raw query")

    def _fill_date_gaps(self, results):
        """
        Ensures the exposure data includes all dates within the experiment's date range.
        For initial dates with no data, adds entries with zero exposures for each variant.
        """
        date_range = self._get_date_range()
        if not date_range.date_from:
            raise ValidationError("Start date is required for experiment exposure data")
        start_date = datetime.fromisoformat(date_range.date_from).date()
        end_date = datetime.fromisoformat(date_range.date_to).date() if date_range.date_to else datetime.now().date()

        result_dict = {}
        variants = set()
        for date, variant, count in results:
            result_dict[(date, variant)] = count
            variants.add(variant)

        complete_results = []
        current_date = start_date
        while current_date <= end_date:
            for variant in variants:
                count = result_dict.get((current_date, variant), 0)
                complete_results.append((current_date, variant, count))
            current_date += timedelta(days=1)

        return complete_results
