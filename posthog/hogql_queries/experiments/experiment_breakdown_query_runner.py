from zoneinfo import ZoneInfo
from typing import Optional
from datetime import datetime, timedelta, UTC

from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
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
        # Default to feature flag events
        exposure_events = ["$feature_flag_called"]

        # Build the exposure query
        exposure_where_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event),
                op=ast.CompareOperationOp.Eq,
            )
            for event in exposure_events
        ]

        # Add feature flag key filter
        exposure_where_conditions.append(
            ast.CompareOperation(
                left=ast.Field(chain=["properties", "$feature_flag_key"]),
                right=ast.Constant(value=self.feature_flag.key),
                op=ast.CompareOperationOp.Eq,
            )
        )

        # Add date range filter
        exposure_where_conditions.extend(
            [
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
            ]
        )

        # Add test account filters
        test_account_filters = self._get_test_accounts_filter()
        if test_account_filters:
            exposure_where_conditions.extend(test_account_filters)

        return ast.SelectQuery(
            select=[
                ast.Field(chain=[self.entity_key]),
                ast.Alias(
                    expr=ast.Call(
                        name="argMin",
                        args=[
                            ast.Field(chain=["properties", "$feature_flag_response"]),
                            ast.Field(chain=["timestamp"]),
                        ],
                    ),
                    alias="first_exposure_variant",
                ),
                ast.Alias(
                    expr=ast.Call(
                        name="min",
                        args=[ast.Field(chain=["timestamp"])],
                    ),
                    alias="first_exposure_time",
                ),
                # Check if user was exposed to multiple variants
                ast.Alias(
                    expr=ast.Call(
                        name="countDistinct",
                        args=[ast.Field(chain=["properties", "$feature_flag_response"])],
                    ),
                    alias="variant_count",
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                alias="exposure_data",
            ),
            where=ast.And(exprs=exposure_where_conditions),
            group_by=[ast.Field(chain=[self.entity_key])],
        )

    def _get_metric_events_query(self, exposure_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns the query for the metric events, joined with exposure data.
        """
        # Get the metric filter based on the metric type
        if self.metric.metric_type == "funnel":
            metric_filter = funnel_steps_to_filter(self.metric.series)
        else:
            # For trends metrics
            metric_filter = event_or_action_to_filter(self.metric.source, self.team)

        # Build the metric events query
        metric_where_conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event),
                op=ast.CompareOperationOp.Eq,
            )
            for event in metric_filter.events
        ]

        # Add time window conditions - events must be after first exposure
        metric_where_conditions.extend(
            [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self.date_range_query.date_from()),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Field(chain=["exposure_data", "first_exposure_time"]),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self.date_range_query.date_to()),
                ),
            ]
        )

        # Add test account filters
        test_account_filters = self._get_test_accounts_filter()
        if test_account_filters:
            metric_where_conditions.extend(test_account_filters)

        return ast.SelectQuery(
            select=[
                ast.Field(chain=[self.entity_key]),
                ast.Field(chain=["event"]),
                ast.Field(chain=["timestamp"]),
                ast.Field(chain=["properties"]),
                # Use $multiple variant if user was exposed to multiple variants
                ast.Alias(
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["exposure_data", "variant_count"]),
                                right=ast.Constant(value=1),
                                op=ast.CompareOperationOp.Gt,
                            ),
                            ast.Constant(value=MULTIPLE_VARIANT_KEY),
                            ast.Field(chain=["exposure_data", "first_exposure_variant"]),
                        ],
                    ),
                    alias="final_variant",
                ),
                ast.Field(chain=["exposure_data", "first_exposure_time"]),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                alias="metric_events",
                join_expr=ast.JoinExpr(
                    table=exposure_query,
                    alias="exposure_data",
                    join_type="INNER",
                    constraint=ast.CompareOperation(
                        left=ast.Field(chain=["metric_events", self.entity_key]),
                        right=ast.Field(chain=["exposure_data", self.entity_key]),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            ),
            where=ast.And(exprs=metric_where_conditions),
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
        tag_queries(
            experiment_id=self.experiment.id,
            team_id=self.team.id,
            query_type="experiment_breakdown",
        )

        # Get exposure data
        exposure_query = self._get_exposure_query()

        # Get metric events with exposure data
        metric_events_query = self._get_metric_events_query(exposure_query)

        # Get breakdown results
        breakdown_query = self._get_breakdown_query(metric_events_query)

        # Execute the query
        result = execute_hogql_query(
            query=breakdown_query,
            team=self.team,
            modifiers=self.modifiers,
            settings=HogQLGlobalSettings(
                max_execution_time=60,
                readonly=2,
            ),
        )

        # Process results
        breakdown_results = []
        for row in result.results:
            variant = row[0] if row[0] else "unknown"
            breakdown_value = row[1] if row[1] else "null"
            count = row[2]
            unique_users = row[3]

            breakdown_results.append(
                {
                    "variant": variant,
                    "breakdown_value": breakdown_value,
                    "count": count,
                    "unique_users": unique_users,
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
