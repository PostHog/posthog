from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, cast

from posthog.hogql import ast

from posthog.hogql_queries.insights.retention.utils import breakdown_extract_expr

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.retention.retention_query_context import RetentionQueryContext


class RetentionBaseQueryBuilder(ABC):
    context: RetentionQueryContext

    def __init__(self, context: RetentionQueryContext):
        self.context = context

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
            self.context.query.samplingFactor is not None
            and isinstance(self.context.query.samplingFactor, float)
            and base_query.select_from is not None
        ):
            base_query.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.context.query.samplingFactor))
            )

    def apply_breakdown(self, base_query: ast.SelectQuery) -> None:
        if not self.context.query.breakdownFilter:
            return

        breakdown_expr = None

        if self.context.query.breakdownFilter.breakdowns:
            # supporting only single breakdowns for now
            breakdown = self.context.query.breakdownFilter.breakdowns[0]
            breakdown_expr = breakdown_extract_expr(
                str(breakdown.property), cast(str, breakdown.type), breakdown.group_type_index
            )
        elif self.context.query.breakdownFilter.breakdown is not None:
            breakdown_expr = breakdown_extract_expr(
                cast(str, self.context.query.breakdownFilter.breakdown),
                cast(str, self.context.query.breakdownFilter.breakdown_type),
                self.context.query.breakdownFilter.breakdown_group_type_index,
            )

        if breakdown_expr:
            base_query.select.append(ast.Alias(alias="breakdown_value", expr=breakdown_expr))
            cast(list[ast.Expr], base_query.group_by).append(ast.Field(chain=["breakdown_value"]))
