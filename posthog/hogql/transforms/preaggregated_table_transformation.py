"""This module contains an AST-to-AST transformation that converts queries on the `events` table to queries on predefined pre-aggregated tables.

These tables are populated by a background process (running in dagster) that aggregates data from the `events` table,
making heavy use of ClickHouse's -state suffix functions, like `uniqState`, to make the calculation at query time much faster.

This is especially useful for queries from very large teams, as the query disk / memory / compute no longer scale linearly with the number of events.

The transformation works by:
* Recursing through the AST to find `SelectQuery` nodes.
* For each `SelectQuery`, check the SELECT, WHERE, and GROUP BY clauses to see if they can be transformed to use pre-aggregated fields.
* If the query can be transformed, it replaces the `events` table with a pre-aggregated table (e.g., `web_stats_daily`).

This transformation doesn't need to be applied to the root query only, e.g. in the case of Trends queries, the inner query
is the one that will be transformed, and the other queries (which are quite complex, making use functions which are hard to optimize like arrayMap) will be left intact.

Exports:
* do_preaggregated_table_transforms
"""

from datetime import datetime
from typing import Optional, TypeVar, cast

import pytz

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.helpers.timestamp_visitor import (
    is_end_of_day_constant,
    is_end_of_hour_constant,
    is_simple_timestamp_field_expression,
    is_start_of_day_constant,
    is_start_of_hour_constant,
)
from posthog.hogql.visitor import CloningVisitor

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import (
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
)

_T_AST = TypeVar("_T_AST", bound=AST)

PREAGGREGATED_TABLE_NAME = "web_pre_aggregated_stats"


def flatten_and(node: Optional[ast.Expr]) -> list[ast.Expr]:
    """Flatten AND expressions in the AST."""
    if node is None:
        return []
    if isinstance(node, ast.And):
        # If it's an AND expression, recursively flatten its children
        flattened_exprs = []
        for expr in node.exprs:
            flattened_child = flatten_and(expr)
            if flattened_child:
                flattened_exprs.extend(flattened_child)
        # Remove any constant True or 1 expressions
        flattened_exprs = [e for e in flattened_exprs if not _is_simple_constant_comparison(e)]
        return flattened_exprs

    if isinstance(node, ast.Call) and node.name == "and":
        return flatten_and(ast.And(exprs=node.args))

    return [node]


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


def is_to_start_of_day_timestamp_field(expr: ast.Call, context: HogQLContext) -> bool:
    """Check if a call represents a toStartOfDay timestamp operation."""
    if (
        expr.name == "toStartOfDay"
        and len(expr.args) == 1
        and is_simple_timestamp_field_expression(expr.args[0], context)
    ):
        return True
    # also accept toStartOfInterval(timestamp, toIntervalDay(1))
    if (
        expr.name == "toStartOfInterval"
        and len(expr.args) == 2
        and is_simple_timestamp_field_expression(expr.args[0], context)
        and isinstance(expr.args[1], ast.Call)
        and expr.args[1].name == "toIntervalDay"
        and len(expr.args[1].args) == 1
        and isinstance(expr.args[1].args[0], ast.Constant)
        and expr.args[1].args[0].value == 1
    ):
        return True
    return False


def is_to_start_of_hour_timestamp_field(expr: ast.Call, context: HogQLContext) -> bool:
    """Check if a call represents a toStartOfHour timestamp operation, or toStartOfX where X is a whole number of hours."""
    if (
        expr.name == "toStartOfHour"
        and len(expr.args) == 1
        and is_simple_timestamp_field_expression(expr.args[0], context)
    ):
        return True
    # also accept toStartOfInterval(timestamp, toIntervalHour(1))
    if (
        expr.name == "toStartOfInterval"
        and len(expr.args) == 2
        and is_simple_timestamp_field_expression(expr.args[0], context)
        and isinstance(expr.args[1], ast.Call)
        and expr.args[1].name == "toIntervalHour"
        and len(expr.args[1].args) == 1
        and isinstance(expr.args[1].args[0], ast.Constant)
        and expr.args[1].args[0].value == 1
    ):
        return True
    return False


def _try_transform_timestamp_comparison_with_start_of_day_time_constant(
    expr: ast.Call, context: HogQLContext
) -> Optional[ast.Call]:
    """
    timestamp >= toStartOfDay('2024-11-24') is equivalent to toStartOfDay(timestamp) >= toStartOfDay('2024-11-24')
    which can be transformed into period_bucket >= toStartOfDay('2024-11-24')

    The valid variants of this expression are:
    timestamp >= toStartOfDay(date) is equivalent to toStartOfDay(timestamp) >= toStartOfDay(date)
    timestamp <  toStartOfDay(date) is equivalent to toStartOfDay(timestamp) <  toStartOfDay(date)
    toStartOfDay(date) <= timestamp is equivalent to toStartOfDay(date) <= toStartOfDay(timestamp)
    toStartOfDay(date) >  timestamp is equivalent to toStartOfDay(date) >  toStartOfDay(timestamp)
    """
    if expr.name not in ["greaterOrEquals", "lessOrEquals", "greater", "less"] or len(expr.args) != 2:
        return None
    arg0 = expr.args[0]
    arg1 = expr.args[1]
    name = expr.name
    if is_simple_timestamp_field_expression(arg0, context):
        if name in ["greaterOrEquals", "less"] and is_start_of_day_constant(arg1):
            return ast.Call(name=name, args=[ast.Field(chain=["period_bucket"]), arg1])
        if name in ["lessOrEquals"] and is_end_of_day_constant(arg1):
            return ast.Call(name=name, args=[ast.Field(chain=["period_bucket"]), arg1])
    if is_simple_timestamp_field_expression(arg1, context):
        if name in ["lessOrEquals", "greater"] and is_start_of_day_constant(arg0):
            return ast.Call(name=expr.name, args=[arg0, ast.Field(chain=["period_bucket"])])
    return None


def _try_transform_timestamp_comparison_with_start_of_hour_time_constant(
    expr: ast.Call, context: HogQLContext
) -> Optional[ast.Call]:
    if expr.name not in ["greaterOrEquals", "lessOrEquals", "greater", "less"] or len(expr.args) != 2:
        return None
    arg0 = expr.args[0]
    arg1 = expr.args[1]
    name = expr.name
    if is_simple_timestamp_field_expression(arg0, context):
        if name in ["greaterOrEquals", "less"] and is_start_of_hour_constant(arg1):
            return ast.Call(name=name, args=[ast.Field(chain=["period_bucket"]), arg1])
        if name in ["lessOrEquals"] and is_end_of_hour_constant(arg1):
            return ast.Call(name=name, args=[ast.Field(chain=["period_bucket"]), arg1])
    if is_simple_timestamp_field_expression(arg1, context):
        if name in ["lessOrEquals", "greater"] and is_start_of_hour_constant(arg0):
            return ast.Call(name=expr.name, args=[arg0, ast.Field(chain=["period_bucket"])])
    return None


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

    if call.distinct:
        return False

    if len(call.args) == 0:
        # count() - valid
        return True
    elif len(call.args) == 1:
        arg = call.args[0]
        return isinstance(arg, ast.Field) and arg.chain == ["*"]

    return False


def _is_uniq_persons_call(call: ast.Call) -> bool:
    """Check if a call is uniq(person_id), count(DISTINCT person_id), or similar for person counting."""
    if len(call.args) != 1:
        return False

    if call.name == "uniq" or (call.name == "count" and call.distinct):
        arg = call.args[0]
        if isinstance(arg, ast.Field):
            return _is_person_id_field(arg)

    return False


def _is_uniq_sessions_call(call: ast.Call) -> bool:
    """Check if a call is uniq(session.id), count(DISTINCT session.id) or similar for session counting."""
    if len(call.args) != 1:
        return False

    if call.name == "uniq" or (call.name == "count" and call.distinct):
        arg = call.args[0]
        if isinstance(arg, ast.Field):
            return _is_session_id_field(arg)

    return False


def _is_simple_constant_comparison(expr: ast.Expr) -> bool:
    """Check if an expression is a simple constant that can be safely ignored."""
    return isinstance(expr, ast.Constant) and expr.value in (1, True, "1")


def _get_supported_field(field: ast.Field) -> tuple[str, ast.Field] | None:
    """
    Check if a field represents a supported property and return (property_name, field) if valid.
    """
    # Handle properties.x pattern
    if len(field.chain) == 2 and field.chain[0] == "properties":
        property_name = field.chain[1]
        if isinstance(property_name, str) and property_name in EVENT_PROPERTY_TO_FIELD:
            return (property_name, ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]]))

    # Handle properties.metadata.x pattern (for nested properties like metadata.loggedIn)
    elif len(field.chain) == 3 and field.chain[0] == "properties":
        property_name = f"{field.chain[1]}.{field.chain[2]}"
        if isinstance(property_name, str) and property_name in EVENT_PROPERTY_TO_FIELD:
            return (property_name, ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]]))

    # Handle events.properties.x pattern
    elif len(field.chain) == 3 and field.chain[0] == "events" and field.chain[1] == "properties":
        property_name = field.chain[2]
        if isinstance(property_name, str) and property_name in EVENT_PROPERTY_TO_FIELD:
            return (property_name, ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]]))

    # Handle events.properties.metadata.x pattern (for nested properties like metadata.loggedIn)
    elif len(field.chain) == 4 and field.chain[0] == "events" and field.chain[1] == "properties":
        property_name = f"{field.chain[2]}.{field.chain[3]}"
        if isinstance(property_name, str) and property_name in EVENT_PROPERTY_TO_FIELD:
            return (property_name, ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]]))

    # Handle session.x pattern
    elif len(field.chain) == 2 and field.chain[0] == "session":
        property_name = field.chain[1]
        if isinstance(property_name, str) and property_name in SESSION_PROPERTY_TO_FIELD:
            return (property_name, ast.Field(chain=[SESSION_PROPERTY_TO_FIELD[property_name]]))

    # Handle events.session.x pattern
    elif len(field.chain) == 3 and field.chain[0] == "events" and field.chain[1] == "session":
        property_name = field.chain[2]
        if isinstance(property_name, str) and property_name in SESSION_PROPERTY_TO_FIELD:
            return (property_name, ast.Field(chain=[SESSION_PROPERTY_TO_FIELD[property_name]]))

    # Handle team_id and events.team_id
    elif (len(field.chain) == 1 and field.chain[0] == "team_id") or (
        len(field.chain) == 2 and field.chain[1] == "team_id"
    ):
        return ("team_id", ast.Field(chain=["team_id"]))

    return None


class ExprTransformer(CloningVisitor):
    """Visitor to transform SELECT expressions to use preaggregated fields."""

    has_transformed_aggregation: bool = False
    seen_aliases: set[str] = set()

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_call(self, node: ast.Call) -> ast.Call:
        if _is_count_pageviews_call(node):
            # count() and count(*) both become sumMerge(pageviews_count_state)
            self.has_transformed_aggregation = True
            return ast.Call(name="sumMerge", args=[ast.Field(chain=["pageviews_count_state"])])
        elif _is_uniq_persons_call(node):
            # uniq(person_id) variants become uniqMerge(persons_uniq_state)
            self.has_transformed_aggregation = True
            return ast.Call(name="uniqMerge", args=[ast.Field(chain=["persons_uniq_state"])])
        elif _is_uniq_sessions_call(node):
            # uniq(session.id) variants become uniqMerge(sessions_uniq_state)
            self.has_transformed_aggregation = True
            return ast.Call(name="uniqMerge", args=[ast.Field(chain=["sessions_uniq_state"])])
        elif is_to_start_of_day_timestamp_field(node, self.context):
            self.has_transformed_aggregation = True
            # toStartOfDay(timestamp) becomes toStartOfDay(period_bucket)
            return ast.Call(name="toStartOfDay", args=[ast.Field(chain=["period_bucket"])])
        elif is_to_start_of_hour_timestamp_field(node, self.context):
            self.has_transformed_aggregation = True
            # toStartOfHour(timestamp) becomes toStartOfHour(period_bucket)
            return ast.Call(name="toStartOfHour", args=[ast.Field(chain=["period_bucket"])])
        elif transformed_call := _try_transform_timestamp_comparison_with_start_of_day_time_constant(
            node, self.context
        ):
            return transformed_call
        elif transformed_call := _try_transform_timestamp_comparison_with_start_of_hour_time_constant(
            node, self.context
        ):
            return transformed_call
        # For other calls, just return the node unchanged
        return super().visit_call(node)

    def visit_field(self, node: ast.Field) -> ast.Field:
        # Transform the field expression
        property_result = _get_supported_field(node)
        if property_result is not None:
            _, field = property_result
            return field
        # if it's referencing an alias we've seen, allow it
        if len(node.chain) == 1 and node.chain[0] in self.seen_aliases:
            return node
        # any other field access is not supported
        raise ValueError("Unsupported field: {}".format(node.chain))

    def visit_compare_operation(self, node: ast.CompareOperation):
        # We already handle this stuff in visit_call, don't duplicate it here
        if node.op == CompareOperationOp.Gt:
            return self.visit(ast.Call(name="greater", args=[node.left, node.right]))
        elif node.op == CompareOperationOp.GtEq:
            return self.visit(ast.Call(name="greaterOrEquals", args=[node.left, node.right]))
        elif node.op == CompareOperationOp.Lt:
            return self.visit(ast.Call(name="less", args=[node.left, node.right]))
        elif node.op == CompareOperationOp.LtEq:
            return self.visit(ast.Call(name="lessOrEquals", args=[node.left, node.right]))
        elif node.op == CompareOperationOp.Eq:
            return self.visit(ast.Call(name="equals", args=[node.left, node.right]))
        elif node.op == CompareOperationOp.NotEq:
            return self.visit(ast.Call(name="notEquals", args=[node.left, node.right]))
        else:
            return super().visit_compare_operation(node)

    def visit_alias(self, node: ast.Alias):
        self.seen_aliases.add(node.alias)
        return super().visit_alias(node)


def _is_constant_one(expr: ast.Expr) -> bool:
    """Check if an expression is a constant with value 1."""
    return isinstance(expr, ast.Constant) and expr.value == 1


def _is_valid_select_from(node: Optional[ast.JoinExpr]) -> bool:
    if not node or not isinstance(node.table, ast.Field):
        return False
    if node.table.chain != ["events"]:
        return False
    if node.constraint:
        return False
    if node.sample:
        sample_value = node.sample.sample_value
        if not _is_constant_one(sample_value.left) or not (
            sample_value.right is None or _is_constant_one(sample_value.right)
        ):
            return False
    return True


def _shallow_transform_select(node: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """Try to apply transformations only to this specific node, without recursing further into the AST."""

    # TODO right now we only have the one preaggregated table that is supported, but in the future could support more.
    # We could even make them unique per team (depending on what the team queries) or allow them to be user-defined.
    table_name = "web_pre_aggregated_stats"

    # Bail if any unsupported part of the SELECT query exist
    # Some of these could be supported in the future, if you add them, make sure you add some tests!
    if (
        node.array_join_list
        or node.array_join_op
        or node.limit_by
        or node.limit_with_ties
        or node.window_exprs
        or node.prewhere
        or node.view_name
        or node.distinct
    ):
        return node

    if not _is_valid_select_from(node.select_from):
        return node

    visitor = ExprTransformer(context)

    try:
        # Transform the SELECT clause
        select = [visitor.visit(expr) for expr in node.select]

        # Transform the WHERE clause, but flatten first
        flat_where = flatten_and(node.where)
        has_pageview_filter = False
        transformed_where = []
        for where_expr in flat_where:
            if is_pageview_filter(where_expr):
                has_pageview_filter = True
            else:
                transformed_where.append(visitor.visit(where_expr))
        if len(transformed_where) > 1:
            where = ast.And(exprs=transformed_where)
        elif len(transformed_where) == 1:
            where = transformed_where[0]
        else:
            where = None

        # Tranform the GROUP BY clause
        group_by = [visitor.visit(expr) for expr in node.group_by] if node.group_by else None
    except ValueError:
        # We ran into an unsupported expression, just return the original node
        return node

    # If we didn't find a pageview filter, we can't use preaggregated tables
    if not has_pageview_filter:
        return node
    # If there was no aggregation in the SELECT clause, we can't use preaggregated tables
    if not visitor.has_transformed_aggregation:
        return node

    # Transform the query to use the preaggregated table
    select_from = ast.JoinExpr(
        table=ast.Field(chain=[table_name]),
        alias=node.select_from.alias if node.select_from else None,
        constraint=None,
        next_join=None,
        sample=None,  # Safe to drop this, as we only support sample=1 anyway
    )

    # Create the transformed query, preserving CTEs from the original
    new_query = ast.SelectQuery(
        select=select,
        select_from=select_from,
        group_by=group_by,
        where=where,
        array_join_list=None,
        array_join_op=None,
        limit_by=None,
        limit_with_ties=None,
        window_exprs=None,
        prewhere=None,
        view_name=None,
        distinct=None,
        limit=node.limit,
        offset=node.offset,
        order_by=node.order_by,
        having=node.having,
        settings=node.settings,
        ctes=node.ctes,  # Preserve CTEs, they should get transformed by the outer visitor
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


def is_integer_timezone(timezone: str) -> bool:
    # we make an assumption that if the timezone offset at the current time is non-integer, it always is, and vice versa
    # this is currently true for all timezones in the tz database
    try:
        parsed = pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        return False
    now = datetime.now()
    offset = parsed.utcoffset(now)
    return offset.total_seconds() % 3600 == 0


def do_preaggregated_table_transforms(node: _T_AST, context: HogQLContext) -> _T_AST:
    """
    This function checks if the query can be transformed to use preaggregated tables.
    If it can, it returns the modified query; otherwise, it returns the original query.
    """

    # Only support the transformation if the team's timezone is set and is an integer number of hours offset
    timezone = context.team.timezone if context.team else None
    if not timezone or not is_integer_timezone(timezone):
        return node

    # Only transform SelectQuery nodes and their nested queries
    if not isinstance(node, ast.SelectQuery | ast.SelectSetQuery):
        return node

    transformer = PreaggregatedTableTransformer(context)
    return cast(_T_AST, transformer.visit(node))
