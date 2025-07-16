from typing import TypeVar, cast

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import CloningVisitor
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
)

_T_AST = TypeVar("_T_AST", bound=AST)


def _is_person_id_field(field: ast.Field) -> bool:
    """Check if a field represents person_id in any of its forms."""
    return field.chain == ["person_id"] or field.chain == ["events", "person", "id"]


def _is_session_id_field(field: ast.Field) -> bool:
    """Check if a field represents session_id in any of its forms."""
    return (
        field.chain == ["session", "id"] or field.chain == ["events", "$session_id"] or field.chain == ["$session_id"]
    )


def _is_count_pageviews_call(call: ast.Call) -> bool:
    """Check if a call is count() or count(*) for pageview counting."""
    if call.name != "count":
        return False

    if len(call.args) == 0:
        # count() - valid
        return True
    elif len(call.args) == 1:
        arg = call.args[0]
        # count(*) - can be either Constant or Field depending on parser
        return (isinstance(arg, ast.Constant) and arg.value == "*") or (
            isinstance(arg, ast.Field) and arg.chain == ["*"]
        )

    return False


def _is_uniq_persons_call(call: ast.Call) -> bool:
    """Check if a call is uniq(person_id) or similar for person counting."""
    if call.name != "uniq":
        return False

    if len(call.args) == 0:
        # uniq() - treat as persons (though not really valid HogQL)
        return True
    elif len(call.args) == 1:
        arg = call.args[0]
        if isinstance(arg, ast.Field):
            return _is_person_id_field(arg)
        elif isinstance(arg, ast.Constant) and arg.value == "*":
            # uniq(*) - treat as persons
            return True

    return False


def _is_uniq_sessions_call(call: ast.Call) -> bool:
    """Check if a call is uniq(session.id) or similar for session counting."""
    if call.name != "uniq":
        return False

    if len(call.args) == 1:
        arg = call.args[0]
        if isinstance(arg, ast.Field):
            return _is_session_id_field(arg)

    return False


def _validate_preaggregated_query(node: ast.SelectQuery, context: HogQLContext) -> bool:
    """Check if a single SelectQuery can be transformed to use preaggregated tables."""

    # Check FROM clause - must be from events table
    if not node.select_from or not isinstance(node.select_from.table, ast.Field):
        return False
    if node.select_from.table.chain != ["events"]:
        return False

    has_pageview_filter = False
    has_unsupported_event = False
    supported_aggregations = set()
    has_sample = False
    sample_value = None

    # Check SAMPLE clause
    if node.select_from.sample:
        has_sample = True
        if isinstance(node.select_from.sample.sample_value, ast.Constant):
            sample_value = node.select_from.sample.sample_value.value
        elif isinstance(node.select_from.sample.sample_value, ast.RatioExpr):
            # Handle ratio expressions like "1" (which becomes RatioExpr with left=1, right=None)
            if node.select_from.sample.sample_value.right is None:
                if isinstance(node.select_from.sample.sample_value.left, ast.Constant):
                    sample_value = node.select_from.sample.sample_value.left.value

    # Check WHERE clause for pageview filter
    if node.where:
        pageview_filter_result = _check_pageview_filter(node.where)
        has_pageview_filter = pageview_filter_result["has_pageview"]
        has_unsupported_event = pageview_filter_result["has_unsupported"]

    # Check SELECT clause for supported aggregations
    for expr in node.select:
        _check_select_expr_for_aggregations(expr, supported_aggregations)

    # Check GROUP BY clause
    if node.group_by:
        for expr in node.group_by:
            if isinstance(expr, ast.Field):
                # Only allow group by fields that are supported
                if len(expr.chain) >= 2 and expr.chain[0] == "properties":
                    property_name = expr.chain[1]
                    # Check if the property is in EVENT_PROPERTY_TO_FIELD mapping
                    if property_name not in EVENT_PROPERTY_TO_FIELD:
                        has_unsupported_event = True
                elif len(expr.chain) >= 2 and expr.chain[0] == "session":
                    # Check if the session property is in SESSION_PROPERTY_TO_FIELD mapping
                    if len(expr.chain) >= 2 and expr.chain[1] not in SESSION_PROPERTY_TO_FIELD:
                        has_unsupported_event = True

    # Must have pageview filter and no unsupported events
    if not has_pageview_filter or has_unsupported_event:
        return False

    # Must have supported aggregations
    if not supported_aggregations:
        return False

    # If sample is specified, it must be 1
    if has_sample and sample_value != 1:
        return False

    return True


def _check_pageview_filter(expr: ast.Expr) -> dict[str, bool]:
    """Check if expression contains pageview filter and unsupported events."""
    has_pageview = False
    has_unsupported = False

    if isinstance(expr, ast.CompareOperation):
        if expr.op == ast.CompareOperationOp.Eq:
            if (
                isinstance(expr.left, ast.Field)
                and expr.left.chain == ["event"]
                and isinstance(expr.right, ast.Constant)
            ):
                if expr.right.value == "$pageview":
                    has_pageview = True
                else:
                    has_unsupported = True
            elif (
                isinstance(expr.right, ast.Field)
                and expr.right.chain == ["event"]
                and isinstance(expr.left, ast.Constant)
            ):
                if expr.left.value == "$pageview":
                    has_pageview = True
                else:
                    has_unsupported = True
    elif isinstance(expr, ast.Call):
        if expr.name == "equals" and len(expr.args) == 2:
            if (
                isinstance(expr.args[0], ast.Field)
                and expr.args[0].chain == ["event"]
                and isinstance(expr.args[1], ast.Constant)
            ):
                if expr.args[1].value == "$pageview":
                    has_pageview = True
                else:
                    has_unsupported = True
    elif isinstance(expr, ast.And):
        for sub_expr in expr.exprs:
            result = _check_pageview_filter(sub_expr)
            has_pageview = has_pageview or result["has_pageview"]
            has_unsupported = has_unsupported or result["has_unsupported"]
    elif isinstance(expr, ast.Or):
        for sub_expr in expr.exprs:
            result = _check_pageview_filter(sub_expr)
            has_pageview = has_pageview or result["has_pageview"]
            has_unsupported = has_unsupported or result["has_unsupported"]
    elif isinstance(expr, ast.Not):
        # For negations, we recursively check but don't change logic
        result = _check_pageview_filter(expr.expr)
        has_pageview = has_pageview or result["has_pageview"]
        has_unsupported = has_unsupported or result["has_unsupported"]
    elif isinstance(expr, ast.Alias):
        result = _check_pageview_filter(expr.expr)
        has_pageview = has_pageview or result["has_pageview"]
        has_unsupported = has_unsupported or result["has_unsupported"]

    return {"has_pageview": has_pageview, "has_unsupported": has_unsupported}


def _check_select_expr_for_aggregations(expr: ast.Expr, supported_aggregations: set[str]) -> None:
    """Check a SELECT expression for supported aggregations."""
    if isinstance(expr, ast.Call):
        if _is_count_pageviews_call(expr):
            supported_aggregations.add("pageviews_count_state")
        elif _is_uniq_persons_call(expr):
            supported_aggregations.add("persons_uniq_state")
        elif _is_uniq_sessions_call(expr):
            supported_aggregations.add("sessions_uniq_state")
    elif isinstance(expr, ast.Alias):
        _check_select_expr_for_aggregations(expr.expr, supported_aggregations)


def _transform_select_expr(expr: ast.Expr) -> ast.Expr:
    """Transform a SELECT expression to use preaggregated fields."""
    if isinstance(expr, ast.Call):
        # Transform aggregations to use preaggregated state fields
        if _is_count_pageviews_call(expr):
            # count() and count(*) both become sumMerge(pageviews_count_state)
            return ast.Call(name="sumMerge", args=[ast.Field(chain=["pageviews_count_state"])])
        elif _is_uniq_persons_call(expr):
            # uniq(person_id) variants become uniqMerge(persons_uniq_state)
            return ast.Call(name="uniqMerge", args=[ast.Field(chain=["persons_uniq_state"])])
        elif _is_uniq_sessions_call(expr):
            # uniq(session.id) variants become uniqMerge(sessions_uniq_state)
            return ast.Call(name="uniqMerge", args=[ast.Field(chain=["sessions_uniq_state"])])
        # Pass through other calls unchanged
        return expr
    elif isinstance(expr, ast.Field):
        # Transform properties.x to the corresponding field in the preaggregated table
        if len(expr.chain) >= 2 and expr.chain[0] == "properties":
            property_name = expr.chain[1]
            if property_name in EVENT_PROPERTY_TO_FIELD:
                return ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]])
        elif len(expr.chain) >= 2 and expr.chain[0] == "session":
            property_name = expr.chain[1]
            if property_name in SESSION_PROPERTY_TO_FIELD:
                return ast.Field(chain=[SESSION_PROPERTY_TO_FIELD[property_name]])
        # Pass through other fields unchanged
        return expr
    elif isinstance(expr, ast.Alias):
        # Transform the inner expression but keep the alias
        return ast.Alias(alias=expr.alias, expr=_transform_select_expr(expr.expr))
    else:
        # Pass through other expressions unchanged
        return expr


def _transform_group_by_expr(expr: ast.Expr) -> ast.Expr:
    """Transform a GROUP BY expression to use preaggregated fields."""
    if isinstance(expr, ast.Field):
        # Transform properties.x to the corresponding field in the preaggregated table
        if len(expr.chain) >= 2 and expr.chain[0] == "properties":
            property_name = expr.chain[1]
            if property_name in EVENT_PROPERTY_TO_FIELD:
                return ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]])
        elif len(expr.chain) >= 2 and expr.chain[0] == "session":
            property_name = expr.chain[1]
            if property_name in SESSION_PROPERTY_TO_FIELD:
                return ast.Field(chain=[SESSION_PROPERTY_TO_FIELD[property_name]])
        # Pass through other fields unchanged
        return expr
    else:
        # Pass through other expressions unchanged
        return expr


def _try_apply_all_transformations(node: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """Try to apply transformations only to this specific query, no looking further into the ast."""

    # Check if the query can be transformed to use preaggregated tables
    if not _validate_preaggregated_query(node, context):
        # Return the node unchanged - it already has any CTEs that were set
        return node

    # For now, we'll use WebStatsCombinedTable for all valid queries
    # In the future, we could add logic to choose between tables based on the query
    table_name = "web_stats_combined"

    # Transform the query to use the preaggregated table
    new_select_from = ast.JoinExpr(
        table=ast.Field(chain=[table_name]),
        alias=node.select_from.alias if node.select_from else None,
        constraint=None,
        next_join=None,
        sample=None,  # Remove sample clause for preaggregated tables
    )

    # Transform SELECT clause
    new_select = [_transform_select_expr(expr) for expr in node.select]

    # Transform GROUP BY clause
    new_group_by = None
    if node.group_by:
        new_group_by = [_transform_group_by_expr(expr) for expr in node.group_by]

    # Create the transformed query, preserving CTEs from the original
    return ast.SelectQuery(
        select=new_select,
        select_from=new_select_from,
        group_by=new_group_by,
        limit=node.limit,
        offset=node.offset,
        order_by=node.order_by,
        having=node.having,
        # Don't include WHERE clause since preaggregated tables already filter to pageviews
        where=None,
        prewhere=None,
        # Preserve all other attributes from the original node
        distinct=node.distinct,
        limit_by=node.limit_by,
        limit_with_ties=node.limit_with_ties,
        settings=node.settings,
        ctes=node.ctes,  # Preserve CTEs
        array_join_op=node.array_join_op,
        array_join_list=node.array_join_list,
        window_exprs=node.window_exprs,
        view_name=node.view_name,
    )


class PreaggregatedTableTransformer(CloningVisitor):
    """Keeps all nodes intact, only implements visit_select_query, where it calls _try_apply_all_transformations."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # First, recursively transform any nested select queries
        transformed_node = cast(ast.SelectQuery, super().visit_select_query(node))

        # Transform CTEs if they exist
        new_ctes = None
        if transformed_node.ctes:
            new_ctes = {}
            for cte_name, cte in transformed_node.ctes.items():
                # Transform the CTE's expression (which should be a SelectQuery)
                if isinstance(cte.expr, ast.SelectQuery):
                    transformed_cte_expr = _try_apply_all_transformations(cte.expr, self.context)
                    new_ctes[cte_name] = ast.CTE(name=cte.name, expr=transformed_cte_expr, cte_type=cte.cte_type)
                else:
                    # Keep the CTE as-is if it's not a SelectQuery
                    new_ctes[cte_name] = cte

        # Create a new SelectQuery with the transformed CTEs
        transformed_with_ctes = ast.SelectQuery(
            select=transformed_node.select,
            select_from=transformed_node.select_from,
            where=transformed_node.where,
            prewhere=transformed_node.prewhere,
            having=transformed_node.having,
            group_by=transformed_node.group_by,
            order_by=transformed_node.order_by,
            limit=transformed_node.limit,
            offset=transformed_node.offset,
            distinct=transformed_node.distinct,
            limit_by=transformed_node.limit_by,
            limit_with_ties=transformed_node.limit_with_ties,
            settings=transformed_node.settings,
            ctes=new_ctes,
            array_join_op=transformed_node.array_join_op,
            array_join_list=transformed_node.array_join_list,
            window_exprs=transformed_node.window_exprs,
            view_name=transformed_node.view_name,
        )

        # Then try to apply transformations to this specific query (not the CTEs)
        return _try_apply_all_transformations(transformed_with_ctes, self.context)


def do_preaggregated_table_transforms(node: _T_AST, context: HogQLContext) -> _T_AST:
    """
    This function checks if the query can be transformed to use preaggregated tables.
    If it can, it returns the modified query; otherwise, it returns the original query.
    """
    # Only transform SelectQuery nodes and their nested queries
    if not isinstance(node, ast.SelectQuery | ast.SelectSetQuery):
        return node

    transformer = PreaggregatedTableTransformer(context)
    return cast(_T_AST, transformer.visit(node))
