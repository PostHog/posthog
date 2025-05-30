from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import (
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ExperimentExposureTimeSeries,
    DateRange,
    IntervalType,
    CachedExperimentExposureQueryResponse,
)
from typing import Optional


class ExperimentExposuresQueryRunner(QueryRunner):
    query: ExperimentExposureQuery
    response: ExperimentExposureQueryResponse
    cached_response: CachedExperimentExposureQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.exposure_criteria = self.query.exposure_criteria
        self.feature_flag_key = self.query.feature_flag.get("key")
        self.group_type_index = self.query.feature_flag.get("filters", {}).get("aggregation_group_type_index")

        multivariate_data = self.query.feature_flag.get("filters", {}).get("multivariate", {})
        self.variants = [variant.get("key") for variant in multivariate_data.get("variants", [])]

        if self.query.holdout:
            self.variants.append(f"holdout-{self.query.holdout.id}")

        self.date_range = self._get_date_range()
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

    def _get_date_range(self) -> DateRange:
        """
        Returns a DateRange object based on the experiment's start and end dates from the query,
        adjusted for the team's timezone if applicable.
        """
        start_date_str = self.query.start_date
        end_date_str = self.query.end_date

        if not start_date_str:
            return DateRange(date_from=None, date_to=None, explicitDate=True)

        start_date = datetime.fromisoformat(start_date_str)
        end_date = datetime.fromisoformat(end_date_str) if end_date_str else None

        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = start_date.astimezone(tz) if start_date else start_date
            end_date = end_date.astimezone(tz) if end_date else end_date

        return DateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

    def _get_test_accounts_filter(self) -> list[ast.Expr]:
        filter_test_accounts = False
        if self.exposure_criteria:
            if hasattr(self.exposure_criteria, "filterTestAccounts"):
                filter_test_accounts = bool(self.exposure_criteria.filterTestAccounts)

        if (
            filter_test_accounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            return [property_to_expr(property, self.team) for property in self.team.test_account_filters]
        return []

    def _get_exposure_query(self) -> ast.SelectQuery:
        exposure_config = None
        if self.exposure_criteria and hasattr(self.exposure_criteria, "exposure_config"):
            exposure_config = self.exposure_criteria.exposure_config

        if exposure_config and hasattr(exposure_config, "event") and exposure_config.event != "$feature_flag_called":
            # For custom exposure events, we extract the event name from the exposure config
            # and get the variant from the $feature/<key> property
            feature_flag_variant_property = f"$feature/{self.feature_flag_key}"
            event = exposure_config.event
        else:
            # For the default $feature_flag_called event, we need to get the variant from $feature_flag_response
            feature_flag_variant_property = "$feature_flag_response"
            event = "$feature_flag_called"

        # Common criteria for all exposure queries
        exposure_conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_range_query.date_to()),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["properties", feature_flag_variant_property]),
                right=ast.Constant(value=self.variants),
            ),
            *self._get_test_accounts_filter(),
        ]

        # Custom exposures can have additional properties to narrow the audience
        if (
            exposure_config
            and hasattr(exposure_config, "kind")
            and exposure_config.kind == "ExperimentEventExposureConfig"
        ):
            exposure_property_filters: list[ast.Expr] = []

            if hasattr(exposure_config, "properties") and exposure_config.properties:
                for property in exposure_config.properties:
                    exposure_property_filters.append(property_to_expr(property, self.team))
            if exposure_property_filters:
                exposure_conditions.append(ast.And(exprs=exposure_property_filters))

        # For the $feature_flag_called events, we need an additional filter to ensure the event is for the correct feature flag
        if event == "$feature_flag_called":
            exposure_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$feature_flag"]),
                    right=ast.Constant(value=self.feature_flag_key),
                ),
            )

        entity = "person_id"
        if isinstance(self.group_type_index, int):
            entity = f"$group_{self.group_type_index}"

        exposure_query = ast.SelectQuery(
            select=[
                ast.Field(chain=["subq", "day"]),
                ast.Field(chain=["subq", "variant"]),
                parse_expr("count(entity_id) as exposed_count"),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(alias="entity_id", expr=ast.Field(chain=[entity])),
                        ast.Alias(
                            alias="variant",
                            expr=parse_expr(
                                "if(count(distinct {variant_property}) > 1, {multiple_variant_key}, any({variant_property}))",
                                placeholders={
                                    "variant_property": ast.Field(chain=["properties", feature_flag_variant_property]),
                                    "multiple_variant_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                                },
                            ),
                        ),
                        parse_expr("toDate(toString(min(timestamp))) as day"),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=ast.And(exprs=exposure_conditions),
                    group_by=[
                        ast.Field(chain=["entity_id"]),
                    ],
                ),
                alias="subq",
            ),
            group_by=[ast.Field(chain=["subq", "day"]), ast.Field(chain=["subq", "variant"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["subq", "day"]), order="ASC")],
        )

        return exposure_query

    def calculate(self) -> ExperimentExposureQueryResponse:
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        tag_queries(
            experiment_id=str(self.query.experiment_id),
            experiment_name=self.query.experiment_name,
            experiment_feature_flag_key=self.feature_flag_key,
        )

        response = execute_hogql_query(
            query_type="ExperimentExposuresQuery",
            query=self._get_exposure_query(),
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
            settings=HogQLGlobalSettings(max_execution_time=180),
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

        # Sort timeseries by original variant order, with MULTIPLE_VARIANT_KEY last
        ordered_timeseries = []

        # Add variants in original order
        for variant in self.variants:
            if variant in variant_series:
                ordered_timeseries.append(variant_series[variant])

        # Add MULTIPLE_VARIANT_KEY last if present
        if MULTIPLE_VARIANT_KEY in variant_series:
            ordered_timeseries.append(variant_series[MULTIPLE_VARIANT_KEY])

        return ExperimentExposureQueryResponse(
            timeseries=ordered_timeseries,
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

        # for draft experiments, return an empty result
        if not date_range.date_from:
            return []

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

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["experiment_exposures_response_version"] = 2
        return payload

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
