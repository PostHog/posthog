from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import EntityType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import entity_to_expr, property_to_expr

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

    def entity_expr_no_props(self, entity: RetentionEntity) -> ast.Expr:
        # Entity matcher with property filters stripped — used to anchor "first ever" against the unfiltered stream.
        # For a data warehouse entity, "presence in the table" is the unfiltered stream, so the predicate is a truthy constant.
        if entity.type == EntityType.DATA_WAREHOUSE:
            return ast.Constant(value=True)
        clean_entity = entity.model_copy(deep=True)
        clean_entity.properties = []
        return entity_to_expr(clean_entity, self.team)

    def entity_expr_with_props(self, entity: RetentionEntity) -> ast.Expr:
        # For data warehouse entities the table itself IS the type matcher, so the "with properties" predicate is
        # just the property filter (or a truthy constant when no properties are configured).
        if entity.type == EntityType.DATA_WAREHOUSE:
            if entity.properties:
                return property_to_expr(entity.properties, self.team)
            return ast.Constant(value=True)
        return entity_to_expr(entity, self.team)

    def entity_timestamp_field(self, entity: RetentionEntity) -> ast.Expr:
        if entity.type == EntityType.DATA_WAREHOUSE:
            if not entity.table_name or not entity.timestamp_field:
                raise ValueError(
                    f"DATA_WAREHOUSE RetentionEntity requires table_name and timestamp_field, "
                    f"got table_name={entity.table_name!r}, timestamp_field={entity.timestamp_field!r}"
                )
            return ast.Field(chain=[entity.table_name, entity.timestamp_field])
        return ast.Field(chain=["events", "timestamp"])

    @cached_property
    def start_entity_expr_no_props(self) -> ast.Expr:
        return self.entity_expr_no_props(self.start_event)

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
    def is_first_ever_occurrence(self) -> bool:
        return self.runner.is_first_ever_occurrence

    @property
    def is_first_occurrence_matching_filters(self) -> bool:
        return self.runner.is_first_occurrence_matching_filters

    @property
    def is_custom_bracket_retention(self) -> bool:
        return self.runner.is_custom_bracket_retention

    @property
    def has_property_aggregation(self) -> bool:
        return self.runner.has_property_aggregation

    @property
    def minimum_occurrences(self) -> int:
        return self.query.retentionFilter.minimumOccurrences or 1

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

    def breakdown_extract_expr_for_query(self) -> ast.Expr | None:
        if not self.query.breakdownFilter:
            return None

        if self.query.breakdownFilter.breakdowns:
            # supporting only single breakdowns for now
            breakdown = self.query.breakdownFilter.breakdowns[0]
            return breakdown_extract_expr(
                str(breakdown.property), cast(str, breakdown.type), breakdown.group_type_index
            )
        if self.query.breakdownFilter.breakdown is not None:
            return breakdown_extract_expr(
                cast(str, self.query.breakdownFilter.breakdown),
                cast(str, self.query.breakdownFilter.breakdown_type),
                self.query.breakdownFilter.breakdown_group_type_index,
            )

        return None

    def apply_breakdown(self, base_query: ast.SelectQuery) -> None:
        breakdown_expr = self.breakdown_extract_expr_for_query()
        if breakdown_expr is None:
            return

        if self.is_first_ever_occurrence:
            # Bucket each user by the breakdown value on their absolute-first
            # start event. Adding breakdown_value to GROUP BY (the else branch)
            # would split each user into one partition per breakdown value they
            # ever had, and the per-partition "first ever" check would silently
            # become "first ever with this value" — letting one user populate
            # multiple buckets. argMinIf reads the breakdown property off the
            # user's earliest start-event row; missing values fall into the
            # empty-string bucket via breakdown_extract_expr's ifNull wrap.
            breakdown_value_expr: ast.Expr = parse_expr(
                "argMinIf({breakdown}, events.timestamp, {entity})",
                {"breakdown": breakdown_expr, "entity": self.start_entity_expr_no_props},
            )
            base_query.select.append(ast.Alias(alias="breakdown_value", expr=breakdown_value_expr))
        else:
            base_query.select.append(ast.Alias(alias="breakdown_value", expr=breakdown_expr))
            cast(list[ast.Expr], base_query.group_by).append(ast.Field(chain=["breakdown_value"]))

    def events_timestamp_filter(self, field: ast.Expr | None = None) -> ast.Expr:
        return self.runner.events_timestamp_filter(field=field)

    def get_first_time_anchor_expr(self, entity: RetentionEntity) -> ast.Expr:
        if not (self.is_first_occurrence_matching_filters or self.is_first_ever_occurrence):
            return ast.Constant(value=None)

        timestamp_field = self.entity_timestamp_field(entity)
        entity_with_properties_expr = self.entity_expr_with_props(entity)

        if self.is_first_ever_occurrence:
            # First-ever occurrence of the target entity, then check filters.
            # We find the timestamp of the first row of this entity, and the first row that also matches properties.
            # If they are the same, this is the user's cohorting event.
            min_ts_expr = parse_expr(
                "minIf({ts}, {expr})",
                {"ts": timestamp_field, "expr": self.entity_expr_no_props(entity)},
            )
            min_ts_with_props_expr = parse_expr(
                "minIf({ts}, {expr})",
                {"ts": timestamp_field, "expr": entity_with_properties_expr},
            )

            return parse_expr(
                "if({min_ts} = {min_ts_with_props}, {min_ts}, NULL)",
                {"min_ts": min_ts_expr, "min_ts_with_props": min_ts_with_props_expr},
            )

        # is_first_occurrence_matching_filters: first occurrence of the target entity that matches filters.
        return parse_expr(
            "minIf({ts}, {expr})",
            {"ts": timestamp_field, "expr": entity_with_properties_expr},
        )
