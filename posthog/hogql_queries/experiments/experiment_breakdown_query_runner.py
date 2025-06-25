from zoneinfo import ZoneInfo
from typing import Optional
from datetime import datetime, timedelta, UTC

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.experiments import (
    MULTIPLE_VARIANT_KEY,
)
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
    event_or_action_to_filter,
)
from posthog.hogql_queries.experiments.funnel_query_utils import (
    funnel_steps_to_filter,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from rest_framework.exceptions import ValidationError
from posthog.schema import (
    ExperimentBreakdownQuery,
    ExperimentBreakdownQueryResponse,
    CachedExperimentBreakdownQueryResponse,
    DateRange,
    IntervalType,
)


class ExperimentBreakdownQueryRunner(QueryRunner):
    query: ExperimentBreakdownQuery
    response: ExperimentBreakdownQueryResponse
    cached_response: CachedExperimentBreakdownQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.group_type_index = self.feature_flag.filters.get("aggregation_group_type_index")
        self.entity_key = "person_id"
        if isinstance(self.group_type_index, int):
            self.entity_key = f"$group_{self.group_type_index}"

        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.date_range = self._get_date_range()
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

        # Determine which statistical method to use
        if self.experiment.stats_config is None:
            self.stats_method = "bayesian"
        else:
            self.stats_method = self.experiment.stats_config.get("method", "bayesian")
            if self.stats_method not in ["bayesian", "frequentist"]:
                self.stats_method = "bayesian"

        # Just to simplify access
        self.metric = self.query.metric

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

    def _get_metric_time_window(self, left: ast.Expr) -> list[ast.CompareOperation]:
        if self.metric.conversion_window is not None and self.metric.conversion_window_unit is not None:
            # Define conversion window as hours after exposure
            time_window_clause = ast.CompareOperation(
                left=left,
                right=ast.Call(
                    name="plus",
                    args=[
                        ast.Field(chain=["exposure_data", "first_exposure_time"]),
                        ast.Call(
                            name="toIntervalSecond",
                            args=[
                                ast.Constant(
                                    value=conversion_window_to_seconds(
                                        self.metric.conversion_window, self.metric.conversion_window_unit
                                    )
                                ),
                            ],
                        ),
                    ],
                ),
                op=ast.CompareOperationOp.Lt,
            )
        else:
            # If no conversion window, just limit to experiment end date
            time_window_clause = ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=left,
                right=ast.Constant(value=self.date_range_query.date_to()),
            )

        return [
            # Improve query performance by only fetching events after the experiment started
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=left,
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
            # Ensure the event occurred after the user was exposed to the experiment
            ast.CompareOperation(
                left=left,
                right=ast.Field(chain=["exposure_data", "first_exposure_time"]),
                op=ast.CompareOperationOp.GtEq,
            ),
            time_window_clause,
        ]

    def _get_test_accounts_filter(self) -> list[ast.Expr]:
        if (
            self.experiment.exposure_criteria
            and self.experiment.exposure_criteria.get("filterTestAccounts")
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            return [property_to_expr(property, self.team) for property in self.team.test_account_filters]
        return []

    def _get_exposure_query(self) -> ast.SelectQuery:
        """
        Returns the query for the exposure data. One row per entity. If an entity is exposed to multiple variants,
        we place them in the $multiple variant.
        """
        # Handle exposure configuration like the main experiment query runner
        exposure_config = (
            self.experiment.exposure_criteria.get("exposure_config") if self.experiment.exposure_criteria else None
        )

        if exposure_config and exposure_config.get("event") != "$feature_flag_called":
            # For custom exposure events, we extract the event name from the exposure config
            # and get the variant from the $feature/<key> property
            feature_flag_variant_property = f"$feature/{self.feature_flag.key}"
            event = exposure_config.get("event")
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
        if exposure_config and exposure_config.get("kind") == "ExperimentEventExposureConfig":
            exposure_property_filters: list[ast.Expr] = []

            if exposure_config.get("properties"):
                for property in exposure_config.get("properties"):
                    exposure_property_filters.append(property_to_expr(property, self.team))
            if exposure_property_filters:
                exposure_conditions.append(ast.And(exprs=exposure_property_filters))

        # For the $feature_flag_called events, we need an additional filter to ensure the event is for the correct feature flag
        if event == "$feature_flag_called":
            exposure_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$feature_flag"]),
                    right=ast.Constant(value=self.feature_flag.key),
                ),
            )

        # Use the same approach as the main experiment query runner
        variant_expression = ast.Alias(
            alias="variant",
            expr=parse_expr(
                "if(count(distinct {variant_property}) > 1, {multiple_variant_key}, any({variant_property}))",
                placeholders={
                    "variant_property": ast.Field(chain=["properties", feature_flag_variant_property]),
                    "multiple_variant_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            ),
        )

        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="entity_id",
                    expr=ast.Field(chain=[self.entity_key]),
                ),
                variant_expression,
                ast.Alias(
                    alias="first_exposure_time",
                    expr=ast.Call(
                        name="min",
                        args=[ast.Field(chain=["timestamp"])],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
            ),
            where=ast.And(exprs=exposure_conditions),
            group_by=[
                ast.Field(chain=[self.entity_key]),
            ],
        )

    def _get_metric_events_query(self, exposure_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns the query for the metric events, joined with exposure data.
        """
        # For funnel metrics, we need to pre-calculate step conditions
        # For each step in the funnel, we create a new column that is 1 if the step is true, 0 otherwise
        step_selects = []
        for i, funnel_step in enumerate(self.metric.series):
            step_filter = event_or_action_to_filter(self.team, funnel_step)
            step_selects.append(
                ast.Alias(
                    alias=f"step_{i}",
                    expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
                )
            )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["events", "timestamp"]),
                ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", self.entity_key])),
                ast.Field(chain=["exposure_data", "variant"]),
                ast.Field(chain=["events", "event"]),
                ast.Field(chain=["events", "uuid"]),
                ast.Field(chain=["events", "properties"]),
                *step_selects,
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                next_join=ast.JoinExpr(
                    table=exposure_query,
                    join_type="INNER JOIN",
                    alias="exposure_data",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["events", self.entity_key]),
                            right=ast.Field(chain=["exposure_data", "entity_id"]),
                            op=ast.CompareOperationOp.Eq,
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            where=ast.And(
                exprs=[
                    *self._get_metric_time_window(left=ast.Field(chain=["events", "timestamp"])),
                    *self._get_test_accounts_filter(),
                    funnel_steps_to_filter(self.team, self.metric.series),
                ],
            ),
        )

    def _get_breakdown_query(self, metric_events_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns the breakdown query that groups events by variant and breakdown value.
        """
        # Determine breakdown field based on the exposure event type
        # For $feature_flag_called events, use $feature_flag_response
        # For other events, use $feature/{flag_key}
        if "$feature_flag_called" in ["$feature_flag_called"]:  # Default exposure event
            breakdown_field = ast.Field(chain=["properties", "$feature_flag_response"])
        else:
            breakdown_field = ast.Field(chain=["properties", f"$feature/{self.feature_flag.key}"])

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["final_variant"]),
                breakdown_field,
                ast.Alias(
                    expr=ast.Call(
                        name="count",
                        args=[ast.Field(chain=["event"])],
                    ),
                    alias="count",
                ),
                ast.Alias(
                    expr=ast.Call(
                        name="countDistinct",
                        args=[ast.Field(chain=[self.entity_key])],
                    ),
                    alias="unique_users",
                ),
            ],
            select_from=ast.JoinExpr(
                table=metric_events_query,
                alias="metric_events",
            ),
            group_by=[
                ast.Field(chain=["final_variant"]),
                breakdown_field,
            ],
            order_by=[
                ast.Field(chain=["final_variant"]),
                ast.Call(
                    name="count",
                    args=[ast.Field(chain=["event"])],
                ),
            ],
        )

    def calculate(self) -> ExperimentBreakdownQueryResponse:
        """
        Calculate the experiment breakdown results.
        """
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        tag_queries(
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=self.feature_flag.key,
        )

        # Get the exposure query
        exposure_query = self._get_exposure_query()

        # Get the metric events query
        metric_events_query = self._get_metric_events_query(exposure_query)

        # Get the breakdown query
        breakdown_query = self._get_breakdown_query(metric_events_query)

        # Execute the query
        result = execute_hogql_query(
            query_type="ExperimentBreakdownQuery",
            query=breakdown_query,
            team=self.team,
            timings=self.timings,
            settings=HogQLGlobalSettings(max_execution_time=180),
        )

        # Transform the results to match the expected format
        breakdown_results = []
        for row in result.results:
            breakdown_results.append(
                {
                    "breakdown_value": row[0],  # variant
                    "count": row[1],  # count
                    "conversion_rate": row[2],  # conversion rate
                }
            )

        return ExperimentBreakdownQueryResponse(
            kind="ExperimentBreakdownQuery",
            results=breakdown_results,
            variants=[*self.variants, MULTIPLE_VARIANT_KEY],  # Include $multiple in variants
            experiment_id=self.experiment.id,
            metric=self.metric,
        )

    def to_query(self) -> ast.SelectQuery:
        """
        Convert the query to a HogQL AST.
        """
        exposure_query = self._get_exposure_query()
        metric_events_query = self._get_metric_events_query(exposure_query)
        return self._get_breakdown_query(metric_events_query)

    def get_cache_payload(self) -> dict:
        """
        Get the cache payload for this query.
        """
        return {
            "experiment_id": self.experiment.id,
            "metric": self.metric.model_dump() if hasattr(self.metric, "model_dump") else self.metric,
            "date_range": self.date_range.model_dump() if hasattr(self.date_range, "model_dump") else self.date_range,
        }

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        """
        Determine the target age for cache entries.
        """
        if lazy:
            return datetime.now(UTC) + timedelta(hours=24)
        return datetime.now(UTC) + timedelta(minutes=30)

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        """
        Determine if the cached results are stale.
        """
        if not last_refresh:
            return True

        if lazy:
            return datetime.now(UTC) - last_refresh > timedelta(hours=24)
        return datetime.now(UTC) - last_refresh > timedelta(minutes=30)
