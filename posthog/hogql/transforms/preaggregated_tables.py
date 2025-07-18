from dataclasses import dataclass
from typing import TypeVar, cast, Optional

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor
from posthog.hogql_queries.web_analytics.pre_aggregated.properties import (
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
)

_T_AST = TypeVar("_T_AST", bound=AST)


@dataclass
class PageviewCheckResult:
    """Result of checking a WHERE clause for pageview filters."""

    has_pageview: bool
    has_unsupported: bool


def flatten_and(node: Optional[ast.Expr]) -> Optional[ast.Expr]:
    """Flatten AND expressions in the AST."""
    if isinstance(node, ast.And):
        # If it's an AND expression, recursively flatten its children
        flattened_exprs = []
        for expr in node.exprs:
            flattened_child = flatten_and(expr)
            if flattened_child:
                flattened_exprs.append(flattened_child)
        # Remove any constant True or 1 expressions
        flattened_exprs = [expr for expr in flattened_exprs if not _is_simple_constant_comparison(expr)]
        if len(flattened_exprs) <= 1:
            return ast.Constant(value=True)
        return ast.And(exprs=flattened_exprs)

    if isinstance(node, ast.Call) and node.name == "and":
        return flatten_and(ast.And(exprs=node.args))

    return node


def is_event_field(field: ast.Field) -> bool:
    """Check if a field represents an event property."""
    return (
        field.chain == ["event"] or (len(field.chain) == 2 and field.chain[1] == "event")  # table_alias.event
    )


def is_pageview_filter(expr: ast.Expr) -> bool:
    """Check if an expression is a straightforward event="$pageview" filter."""
    if isinstance(expr, ast.CompareOperation) and expr.op == CompareOperationOp.Eq:
        if isinstance(expr.left, ast.Field) and is_event_field(expr.left):
            return isinstance(expr.right, ast.Constant) and expr.right.value == "$pageview"
        if isinstance(expr.right, ast.Field) and is_event_field(expr.right):
            return isinstance(expr.left, ast.Constant) and expr.left.value == "$pageview"
        if (
            isinstance(expr.left, ast.Alias)
            and isinstance(expr.left.expr, ast.Field)
            and is_event_field(expr.left.expr)
        ):
            return isinstance(expr.right, ast.Constant) and expr.right.value == "$pageview"
        if (
            isinstance(expr.right, ast.Alias)
            and isinstance(expr.right.expr, ast.Field)
            and is_event_field(expr.right.expr)
        ):
            return isinstance(expr.left, ast.Constant) and expr.left.value == "$pageview"
    if isinstance(expr, ast.Call) and expr.name == "equals" and len(expr.args) == 2:
        return is_pageview_filter(ast.CompareOperation(left=expr.args[0], right=expr.args[1], op=CompareOperationOp.Eq))
    return False


def is_timestamp_field(field: ast.Expr) -> bool:
    """Check if a field represents a timestamp."""
    if not isinstance(field, ast.Field):
        return False

    return (
        field.chain == ["timestamp"]
        or (len(field.chain) == 2 and field.chain[1] == "timestamp")  # table_alias.timestamp
    )


def is_to_start_of_day_timestamp_call(expr: ast.Call) -> bool:
    """Check if a call represents a toStartOfDay timestamp operation."""
    if expr.name == "toStartOfDay" and len(expr.args) == 1 and is_timestamp_field(expr.args[0]):
        return True
    # also accept toStartOfInterval(timestamp, toIntervalDay(1))
    if (
        expr.name == "toStartOfInterval"
        and len(expr.args) == 2
        and is_timestamp_field(expr.args[0])
        and isinstance(expr.args[1], ast.Call)
        and expr.args[1].name == "toIntervalDay"
        and len(expr.args[1].args) == 1
        and isinstance(expr.args[1].args[0], ast.Constant)
        and expr.args[1].args[0].value == 1
    ):
        return True
    return False


class CheckedUnsupportedWhereClauseVisitor(TraversingVisitor):
    """Visitor to check if the query references the event column."""

    has_unsupported_where_clause: bool

    def __init__(self) -> None:
        super().__init__()
        self.has_unsupported_where_clause = False

    def visit_field(self, node: ast.Field) -> None:
        # Any references to anything BUT supported event/session properties or timestamp is unsupported
        is_supported_property = _get_supported_property_field(node)
        is_timestamp = is_timestamp_field(node)
        if not is_supported_property and not is_timestamp:
            self.has_unsupported_where_clause = True


def _check_unsupported_expr_for_where_clause(node: ast.Expr) -> bool:
    """Check if the query references the event column."""
    checker = CheckedUnsupportedWhereClauseVisitor()
    checker.visit(node)
    return checker.has_unsupported_where_clause


def _check_where_clause(expr: Optional[ast.Expr]) -> bool:
    """Check if expression contains straightforward event="$pageview" and no other event filters."""
    # Flatten the where clause to make life a bit easier
    expr = flatten_and(expr)

    if not expr:
        return False

    if isinstance(expr, ast.And):
        exprs = expr.exprs
    else:
        exprs = [expr]

    # Exactly one top-level expr here should be an equality check for event="$pageview"
    has_pageview = False
    for sub_expr in exprs:
        # is this sub_expr an equality check for event="$pageview"?
        if is_pageview_filter(sub_expr):
            if has_pageview:
                # More than one pageview filter - not allowed
                return False
            has_pageview = True
        elif _check_unsupported_expr_for_where_clause(sub_expr):
            # If it references event but is not a pageview filter, it's unsupported
            return False

    return has_pageview


def _is_person_id_field(field: ast.Field) -> bool:
    """Check if a field represents person_id in any of its forms."""

    # TODO for the table_alias check, also look at the FROM part of the SELECT
    return (
        field.chain == ["person_id"]
        or field.chain == ["person", "id"]  # person.id
        or field.chain == ["events", "person_id"]  # events.person_id
        or field.chain == ["events", "person", "id"]  # events.person.id
        or (len(field.chain) == 2 and field.chain[1] == "person_id")  # table_alias.person_id
        or (len(field.chain) == 3 and field.chain[1:] == ["person", "id"])  # table_alias.person.id
    )


def _is_session_id_field(field: ast.Field) -> bool:
    """Check if a field represents session_id in any of its forms."""

    # TODO for the table_alias check, also look at the FROM part of the SELECT
    return (
        field.chain == ["session", "id"]  # session.id
        or field.chain == ["events", "session", "id"]  # events.session.id
        or field.chain == ["events", "$session_id"]  # events.$session_id
        or field.chain == ["$session_id"]  # $session_id
        or (len(field.chain) == 2 and field.chain[1] == "$session_id")  # table_alias.$session_id
        or (len(field.chain) == 3 and field.chain[1:] == ["session", "id"])  # table_alias.session.id
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
        return isinstance(arg, ast.Field) and arg.chain == ["*"]

    return False


def _is_uniq_persons_call(call: ast.Call) -> bool:
    """Check if a call is uniq(person_id) or similar for person counting."""
    if call.name != "uniq":
        return False

    if len(call.args) == 1:
        arg = call.args[0]
        if isinstance(arg, ast.Field):
            return _is_person_id_field(arg)

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
    # TODO simplify this by just throwing on something invalid

    # Check FROM clause - must be from events table
    if not node.select_from or not isinstance(node.select_from.table, ast.Field):
        return False
    if node.select_from.table.chain != ["events"]:
        return False

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
    if not _check_where_clause(node.where):
        return False

    # Check SELECT clause for supported aggregations
    for expr in node.select:
        if not _is_select_expr_valid(expr):
            return False

    # Check GROUP BY clause
    if node.group_by:
        for expr in node.group_by:
            if isinstance(expr, ast.Field):
                # Check if this looks like a property field pattern
                # Only reject if it's a property-like pattern that's not supported
                is_property_pattern = (
                    (len(expr.chain) >= 2 and expr.chain[0] == "properties")
                    or (len(expr.chain) >= 3 and expr.chain[0] == "events" and expr.chain[1] == "properties")
                    or (len(expr.chain) >= 2 and expr.chain[0] == "session")
                    or (len(expr.chain) >= 3 and expr.chain[0] == "events" and expr.chain[1] == "session")
                )

                if is_property_pattern and _get_supported_property_field(expr) is None:
                    return False

    # If sample is specified, it must be 1
    if has_sample and sample_value != 1:
        return False

    return True


def _is_simple_constant_comparison(expr: ast.Expr) -> bool:
    """Check if an expression is a simple constant that can be safely ignored."""
    return isinstance(expr, ast.Constant) and expr.value in (1, True, "1")


def _is_safe_timestamp_comparison(call: ast.Call) -> bool:
    """Check if a function call is a safe timestamp comparison that can be ignored during validation."""
    # Common timestamp comparison functions that don't affect aggregation logic
    timestamp_functions = {
        "greaterOrEquals",
        "lessOrEquals",
        "greater",
        "less",
        "greaterEquals",
        "lessEquals",
        "gte",
        "lte",
        "gt",
        "lt",
    }

    if call.name not in timestamp_functions:
        return False

    if len(call.args) != 2:
        return False

    # Check if first argument is likely a timestamp field
    first_arg = call.args[0]
    if isinstance(first_arg, ast.Field):
        # Allow timestamp field comparisons
        if first_arg.chain == ["timestamp"] or (len(first_arg.chain) == 2 and first_arg.chain[1] == "timestamp"):
            return True

    return False


def _get_supported_property_field(field: ast.Field) -> tuple[str, str] | None:
    """
    Check if a field represents a supported property and return (property_name, field_name) if valid.

    Returns:
        tuple[str, str] | None: (property_name, field_name) if supported, None otherwise
    """
    # Handle properties.x pattern
    if len(field.chain) == 2 and field.chain[0] == "properties":
        property_name = field.chain[1]
        if isinstance(property_name, str) and property_name in EVENT_PROPERTY_TO_FIELD:
            return (property_name, EVENT_PROPERTY_TO_FIELD[property_name])

    # Handle events.properties.x pattern
    elif len(field.chain) == 3 and field.chain[0] == "events" and field.chain[1] == "properties":
        property_name = field.chain[2]
        if isinstance(property_name, str) and property_name in EVENT_PROPERTY_TO_FIELD:
            return (property_name, EVENT_PROPERTY_TO_FIELD[property_name])

    # Handle session.x pattern
    elif len(field.chain) == 2 and field.chain[0] == "session":
        property_name = field.chain[1]
        if isinstance(property_name, str) and property_name in SESSION_PROPERTY_TO_FIELD:
            return (property_name, SESSION_PROPERTY_TO_FIELD[property_name])

    # Handle events.session.x pattern
    elif len(field.chain) == 3 and field.chain[0] == "events" and field.chain[1] == "session":
        property_name = field.chain[2]
        if isinstance(property_name, str) and property_name in SESSION_PROPERTY_TO_FIELD:
            return (property_name, SESSION_PROPERTY_TO_FIELD[property_name])

    return None


def _is_select_expr_valid(expr: ast.Expr) -> bool:
    """Check a SELECT expression for supported aggregations."""
    if isinstance(expr, ast.Call):
        if _is_count_pageviews_call(expr):
            return True
        elif _is_uniq_persons_call(expr):
            return True
        elif _is_uniq_sessions_call(expr):
            return True
        if is_to_start_of_day_timestamp_call(expr):
            return True
    elif isinstance(expr, ast.Alias):
        return _is_select_expr_valid(expr.expr)
    elif isinstance(expr, ast.Field):
        # Check if this is a supported property field
        property_result = _get_supported_property_field(expr)
        return property_result is not None
    return False


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
        elif is_to_start_of_day_timestamp_call(expr):
            # toStartOfDay(timestamp) becomes toStartOfDay(period_bucket)
            return ast.Call(name="toStartOfDay", args=[ast.Field(chain=["period_bucket"])])

    elif isinstance(expr, ast.Field):
        # Transform properties.x to the corresponding field in the preaggregated table
        property_result = _get_supported_property_field(expr)
        if property_result is not None:
            property_name, field_name = property_result
            return ast.Field(chain=[field_name])
    elif isinstance(expr, ast.Alias):
        # Transform the inner expression but keep the alias
        return ast.Alias(alias=expr.alias, expr=_transform_select_expr(expr.expr))

    raise ValueError("Unsupported expression type in SELECT clause: {}".format(type(expr)))


def _transform_group_by_expr(expr: ast.Expr) -> ast.Expr:
    """Transform a GROUP BY expression to use preaggregated fields."""
    if isinstance(expr, ast.Field):
        # Transform properties.x to the corresponding field in the preaggregated table
        property_result = _get_supported_property_field(expr)
        if property_result is not None:
            property_name, field_name = property_result
            return ast.Field(chain=[field_name])
        # Pass through other fields unchanged
        return expr
    else:
        # Pass through other expressions unchanged
        return expr


def _shallow_transform_select(node: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """Try to apply transformations only to this specific query"""

    # TODO this should iterate over all possible preaggregated tables and apply the best one
    table_name = "web_stats_daily"

    # Check if the query can be transformed to use preaggregated tables
    if not _validate_preaggregated_query(node, context):
        # Return the node unchanged - it already has any CTEs that were set
        return node

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
    new_query = ast.SelectQuery(
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
    return new_query


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
                    transformed_cte_expr = _shallow_transform_select(cte.expr, self.context)
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
        return _shallow_transform_select(transformed_with_ctes, self.context)


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
