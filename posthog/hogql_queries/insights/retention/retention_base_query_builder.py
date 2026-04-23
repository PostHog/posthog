from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import entity_to_expr

from posthog.hogql_queries.insights.retention.utils import breakdown_extract_expr

if TYPE_CHECKING:
    from posthog.schema import RetentionEntity, RetentionQuery

    from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner
    from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
    from posthog.models import Team


class RetentionBaseQueryBuilder(ABC):
    runner: RetentionQueryRunner

    def __init__(self, runner: RetentionQueryRunner):
        self.runner = runner

    @property
    def team(self) -> Team:
        return self.runner.team

    @property
    def query(self) -> RetentionQuery:
        return self.runner.query

    @property
    def query_date_range(self) -> QueryDateRangeWithIntervals:
        return self.runner.query_date_range

    @property
    def start_event(self) -> RetentionEntity:
        return self.runner.start_event

    @property
    def return_event(self) -> RetentionEntity:
        return self.runner.return_event

    @property
    def start_entity_expr(self) -> ast.Expr:
        return self.runner.start_entity_expr

    @property
    def return_entity_expr(self) -> ast.Expr:
        return self.runner.return_entity_expr

    @property
    def aggregation_target_events_column(self) -> str:
        return self.runner.aggregation_target_events_column

    @property
    def property_aggregation_expr(self) -> ast.Expr | None:
        return self.runner.property_aggregation_expr

    @property
    def global_event_filters(self) -> list[ast.Expr]:
        return self.runner.global_event_filters

    @property
    def events_timestamp_filter(self) -> ast.Expr:
        return self.runner.events_timestamp_filter

    @property
    def is_first_ever_occurrence(self) -> bool:
        return self.runner.is_first_ever_occurrence

    @property
    def is_first_occurrence_matching_filters(self) -> bool:
        return self.runner.is_first_occurrence_matching_filters

    @property
    def is_custom_bracket_retention(self) -> bool:
        return self.runner.is_custom_bracket_retention

    def build(
        self,
        start_interval_index_filter: Optional[int] = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        base_query = self.build_base_query(
            start_interval_index_filter=start_interval_index_filter,
            selected_breakdown_value=selected_breakdown_value,
        )
        self.apply_sampling(base_query)
        self.apply_breakdown(base_query)
        return base_query

    @abstractmethod
    def build_base_query(
        self,
        start_interval_index_filter: Optional[int] = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery: ...

    def apply_sampling(self, base_query: ast.SelectQuery) -> None:
        if (
            self.query.samplingFactor is not None
            and isinstance(self.query.samplingFactor, float)
            and base_query.select_from is not None
        ):
            base_query.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

    def apply_breakdown(self, base_query: ast.SelectQuery) -> None:
        if not self.query.breakdownFilter:
            return

        breakdown_expr = None

        if self.query.breakdownFilter.breakdowns:
            # supporting only single breakdowns for now
            breakdown = self.query.breakdownFilter.breakdowns[0]
            breakdown_expr = breakdown_extract_expr(
                str(breakdown.property), cast(str, breakdown.type), breakdown.group_type_index
            )
        elif self.query.breakdownFilter.breakdown is not None:
            breakdown_expr = breakdown_extract_expr(
                cast(str, self.query.breakdownFilter.breakdown),
                cast(str, self.query.breakdownFilter.breakdown_type),
                self.query.breakdownFilter.breakdown_group_type_index,
            )

        if breakdown_expr:
            base_query.select.append(ast.Alias(alias="breakdown_value", expr=breakdown_expr))
            cast(list[ast.Expr], base_query.group_by).append(ast.Field(chain=["breakdown_value"]))

    def get_first_time_anchor_expr(self) -> ast.Expr:
        if self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence:
            start_entity_with_properties_expr = entity_to_expr(self.start_event, self.team)

            if self.is_first_ever_occurrence:
                # Create a clean entity without properties to find the true first-ever event
                clean_start_event = self.start_event.model_copy(deep=True)
                clean_start_event.properties = []
                start_entity_expr_no_props = entity_to_expr(clean_start_event, self.team)

                # First-ever occurrence of the target event, then check filters.
                # We find the timestamp of the first event of this type, and the first event of this type that also matches properties.
                # If they are the same, this is the user's cohorting event.
                min_ts_expr = parse_expr("minIf(events.timestamp, {expr})", {"expr": start_entity_expr_no_props})
                min_ts_with_props_expr = parse_expr(
                    "minIf(events.timestamp, {expr})", {"expr": start_entity_with_properties_expr}
                )

                return parse_expr(
                    "if({min_ts} = {min_ts_with_props}, {min_ts}, NULL)",
                    {"min_ts": min_ts_expr, "min_ts_with_props": min_ts_with_props_expr},
                )
            else:  # is_first_occurrence_matching_filters
                # First occurrence of the target event that matches filters.
                return parse_expr("minIf(events.timestamp, {expr})", {"expr": start_entity_with_properties_expr})
        else:
            return ast.Constant(value=None)
