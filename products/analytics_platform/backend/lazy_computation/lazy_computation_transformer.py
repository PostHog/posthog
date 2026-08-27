import uuid
from datetime import datetime, timedelta
from typing import Optional, Union

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.helpers.timestamp_visitor import is_simple_timestamp_field_expression
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationExecutor,
    LazyComputationQuery,
    LazyComputationResult,
    LazyComputationTable,
)

PREAGGREGATED_DAILY_UNIQUE_PERSONS_PAGEVIEWS_TABLE_NAME = DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()


def _is_person_id_field(field: ast.Field) -> bool:
    """Check if a field represents person_id in any of its forms."""
    return (
        field.chain == ["person_id"]
        or field.chain == ["person", "id"]  # person.id
        or field.chain == ["events", "person_id"]  # events.person_id
        or field.chain == ["events", "person", "id"]  # events.person.id
        or (len(field.chain) == 2 and field.chain[1] == "person_id")  # table_alias.person_id
        or (len(field.chain) == 3 and field.chain[1:] == ["person", "id"])  # table_alias.person.id
    )


def _is_timestamp_field(expr: ast.Expr, context: HogQLContext) -> bool:
    """Check if an expression is a simple timestamp field."""
    # Use the robust timestamp field detection from timestamp_visitor
    if is_simple_timestamp_field_expression(expr, context):
        return True

    # Also handle simple field patterns for unresolved ASTs
    if isinstance(expr, ast.Field):
        return (
            expr.chain == ["timestamp"]
            or expr.chain == ["events", "timestamp"]
            or (len(expr.chain) == 2 and expr.chain[1] == "timestamp")
        )
    return False


def _is_event_field(field: ast.Field) -> bool:
    """Check if a field represents an event property."""
    return field.chain == ["event"] or (len(field.chain) == 2 and field.chain[1] == "event")


def _is_pageview_filter(expr: ast.Expr) -> bool:
    """Check if an expression is a straightforward event='$pageview' filter."""
    if isinstance(expr, ast.CompareOperation) and expr.op == CompareOperationOp.Eq:
        if isinstance(expr.left, ast.Field) and _is_event_field(expr.left):
            return isinstance(expr.right, ast.Constant) and expr.right.value == "$pageview"
        if isinstance(expr.right, ast.Field) and _is_event_field(expr.right):
            return isinstance(expr.left, ast.Constant) and expr.left.value == "$pageview"
    if isinstance(expr, ast.Call) and expr.name == "equals" and len(expr.args) == 2:
        return _is_pageview_filter(
            ast.CompareOperation(left=expr.args[0], right=expr.args[1], op=CompareOperationOp.Eq)
        )
    return False


def _is_uniq_exact_persons_call(expr: ast.Expr) -> bool:
    """Check if expression is uniqExact(person_id) or count(DISTINCT person_id)."""
    if not isinstance(expr, ast.Call):
        return False

    # uniqExact(person_id)
    if expr.name == "uniqExact" and len(expr.args) == 1:
        arg = expr.args[0]
        if isinstance(arg, ast.Field) and _is_person_id_field(arg):
            return True

    # count(DISTINCT person_id)
    if expr.name == "count" and expr.distinct and len(expr.args) == 1:
        arg = expr.args[0]
        if isinstance(arg, ast.Field) and _is_person_id_field(arg):
            return True

    return False


def _is_to_start_of_day_timestamp(expr: ast.Expr, context: HogQLContext) -> bool:
    """Check if expression is toStartOfDay(timestamp) or toStartOfInterval(timestamp, toIntervalDay(1))."""
    if not isinstance(expr, ast.Call):
        return False

    # toStartOfDay(timestamp)
    if expr.name == "toStartOfDay" and len(expr.args) == 1 and _is_timestamp_field(expr.args[0], context):
        return True

    # toStartOfInterval(timestamp, toIntervalDay(1))
    if (
        expr.name == "toStartOfInterval"
        and len(expr.args) == 2
        and _is_timestamp_field(expr.args[0], context)
        and isinstance(expr.args[1], ast.Call)
        and expr.args[1].name == "toIntervalDay"
        and len(expr.args[1].args) == 1
        and isinstance(expr.args[1].args[0], ast.Constant)
        and expr.args[1].args[0].value == 1
    ):
        return True

    return False


def _unwrap_alias(expr: ast.Expr) -> ast.Expr:
    """Unwrap an Alias node to get the underlying expression."""
    if isinstance(expr, ast.Alias):
        return expr.expr
    return expr


def _call_to_compare_op(call_name: str) -> CompareOperationOp:
    """Convert a comparison call name to CompareOperationOp."""
    mapping = {
        "greaterOrEquals": CompareOperationOp.GtEq,
        "greater": CompareOperationOp.Gt,
        "less": CompareOperationOp.Lt,
        "lessOrEquals": CompareOperationOp.LtEq,
        "equals": CompareOperationOp.Eq,
        "notEquals": CompareOperationOp.NotEq,
    }
    return mapping.get(call_name, CompareOperationOp.Eq)


def _extract_datetime_constant(expr: ast.Expr, context: HogQLContext) -> Optional[datetime]:
    """Extract a datetime from a constant or wrapped constant expression.

    Handles patterns like:
    - '2024-01-01' (direct constant)
    - toDateTime('2024-01-01 00:00:00')
    - toStartOfDay('2024-01-01')
    - assumeNotNull(toDateTime('2024-01-01 00:00:00'))
    - toStartOfInterval(assumeNotNull(toDateTime('2024-01-01')), toIntervalDay(1))
    """
    # Direct constant: '2024-01-01' or datetime object
    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, datetime):
            return expr.value
        if isinstance(expr.value, str):
            try:
                # Try parsing ISO format
                dt_str = expr.value.replace("Z", "+00:00")
                return datetime.fromisoformat(dt_str)
            except (ValueError, AttributeError):
                return None

    # Handle wrapper functions that pass through to their first argument
    if isinstance(expr, ast.Call) and expr.name in ["toDateTime", "toStartOfDay", "assumeNotNull"]:
        if len(expr.args) > 0:
            return _extract_datetime_constant(expr.args[0], context)

    # Handle toStartOfInterval(arg, toIntervalDay(1)) - extract datetime from first arg
    if isinstance(expr, ast.Call) and expr.name == "toStartOfInterval" and len(expr.args) >= 1:
        return _extract_datetime_constant(expr.args[0], context)

    return None


def _is_timestamp_or_start_of_day_timestamp(expr: ast.Expr, context: HogQLContext) -> bool:
    """Check if an expression is either a timestamp field or toStartOfDay(timestamp)."""
    # Direct timestamp field
    if _is_timestamp_field(expr, context):
        return True

    # toStartOfDay(timestamp) or toStartOfInterval(timestamp, toIntervalDay(1))
    if isinstance(expr, ast.Call):
        return _is_to_start_of_day_timestamp(expr, context)

    return False


_LOWER_BOUND_OPS = [CompareOperationOp.GtEq, CompareOperationOp.Gt]
_UPPER_BOUND_OPS = [CompareOperationOp.Lt, CompareOperationOp.LtEq]


def _as_compare_operation(expr: ast.Expr) -> Optional[ast.CompareOperation]:
    """Return a CompareOperation for a compare expression, converting comparison calls."""
    if isinstance(expr, ast.CompareOperation):
        return expr
    if isinstance(expr, ast.Call) and expr.name in ["greaterOrEquals", "greater", "less", "lessOrEquals"]:
        if len(expr.args) == 2:
            return ast.CompareOperation(left=expr.args[0], right=expr.args[1], op=_call_to_compare_op(expr.name))
    return None


def _is_timestamp_filter(expr: ast.Expr, context: HogQLContext) -> bool:
    """Check if a WHERE expression compares a timestamp field against a bound."""
    compare_expr = _as_compare_operation(expr)
    if compare_expr is None:
        return False
    return _is_timestamp_or_start_of_day_timestamp(
        compare_expr.left, context
    ) or _is_timestamp_or_start_of_day_timestamp(compare_expr.right, context)


def _combine_and(exprs: list[ast.Expr]) -> Optional[ast.Expr]:
    """Combine expressions with AND, collapsing the empty and single cases."""
    if not exprs:
        return None
    if len(exprs) == 1:
        return exprs[0]
    return ast.And(exprs=exprs)


def _extract_bound(
    compare_expr: ast.CompareOperation, context: HogQLContext
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Return (start, end) contributed by one timestamp comparison. Both None if it is not one."""
    # timestamp <op> constant
    if _is_timestamp_or_start_of_day_timestamp(compare_expr.left, context):
        value = _extract_datetime_constant(compare_expr.right, context)
        if compare_expr.op in _LOWER_BOUND_OPS:
            return value, None
        if compare_expr.op in _UPPER_BOUND_OPS:
            return None, value

    # constant <op> timestamp (bounds reverse)
    elif _is_timestamp_or_start_of_day_timestamp(compare_expr.right, context):
        value = _extract_datetime_constant(compare_expr.left, context)
        if compare_expr.op in _UPPER_BOUND_OPS:
            return value, None
        if compare_expr.op in _LOWER_BOUND_OPS:
            return None, value

    return None, None


def _extract_timestamp_range(where_exprs: list[ast.Expr], context: HogQLContext) -> Optional[tuple[datetime, datetime]]:
    """
    Extract start and end timestamps from WHERE conditions.
    Handles both:
      - timestamp >= '2025-01-01'
      - toStartOfDay(timestamp) >= '2025-01-01'
    Returns (start, end) as datetime objects, or None if not found.
    """
    start_dt = None
    end_dt = None

    for expr in where_exprs:
        compare_expr = _as_compare_operation(expr)
        if compare_expr is None:
            continue

        start, end = _extract_bound(compare_expr, context)
        start_dt = start or start_dt
        end_dt = end or end_dt

    # Require both bounds
    if not start_dt or not end_dt:
        return None

    return start_dt, end_dt


def _flatten_and(node: Optional[ast.Expr]) -> list[ast.Expr]:
    """Flatten AND expressions in the AST."""
    if node is None:
        return []
    if isinstance(node, ast.And):
        # If it's an AND expression, recursively flatten its children
        flattened_exprs = []
        for expr in node.exprs:
            flattened_child = _flatten_and(expr)
            if flattened_child:
                flattened_exprs.extend(flattened_child)
        return flattened_exprs

    if isinstance(node, ast.Call) and node.name == "and":
        return _flatten_and(ast.And(exprs=node.args))

    return [node]


def _is_constant_one(expr: ast.Expr) -> bool:
    """Check if an expression is a constant with value 1."""
    return isinstance(expr, ast.Constant) and expr.value == 1


def _is_valid_events_from(select_from: Optional[ast.JoinExpr]) -> bool:
    """Check if the FROM clause is a simple events table reference."""
    if not select_from or not isinstance(select_from.table, ast.Field):
        return False
    if select_from.table.chain != ["events"]:
        return False
    # No joins allowed
    if select_from.next_join or select_from.constraint:
        return False
    # Allow SAMPLE 1 (or no sample), but not other sample values
    if select_from.sample:
        sample_value = select_from.sample.sample_value
        if not _is_constant_one(sample_value.left) or not (
            sample_value.right is None or _is_constant_one(sample_value.right)
        ):
            return False
    return True


def _build_select_aliases(node: ast.SelectQuery, context: HogQLContext) -> dict[Union[str, int], ast.Expr]:
    """Build a mapping of alias names to their underlying expressions from SELECT."""
    aliases: dict[Union[str, int], ast.Expr] = {}
    if node.select:
        for select_expr in node.select:
            if isinstance(select_expr, ast.Alias):
                aliases[select_expr.alias] = select_expr.expr
    return aliases


def _resolve_alias_in_group_by(
    expr: ast.Expr, aliases: dict[Union[str, int], ast.Expr], context: HogQLContext
) -> ast.Expr:
    """Resolve an alias reference in GROUP BY to its underlying expression."""
    # If it's a single-element field that matches an alias, return the aliased expression
    if isinstance(expr, ast.Field) and len(expr.chain) == 1:
        alias_name = expr.chain[0]
        if alias_name in aliases:
            return aliases[alias_name]
    return expr


def _select_is_uniq_persons_daily(node: ast.SelectQuery, context: HogQLContext) -> bool:
    """SELECT must have 1-2 expressions: uniqExact(person_id) and optionally toStartOfDay(timestamp)."""
    if not node.select or len(node.select) < 1 or len(node.select) > 2:
        return False

    has_uniq_exact = False
    for select_expr in node.select:
        expr = _unwrap_alias(select_expr)
        if _is_uniq_exact_persons_call(expr):
            has_uniq_exact = True
        elif not _is_to_start_of_day_timestamp(expr, context):
            return False  # Unknown expression type
    return has_uniq_exact


def _group_by_starts_with_day(node: ast.SelectQuery, context: HogQLContext) -> bool:
    """First GROUP BY expression must be toStartOfDay(timestamp), resolving SELECT aliases."""
    if not node.group_by:
        return False
    aliases = _build_select_aliases(node, context)
    first_group_expr = _unwrap_alias(node.group_by[0])
    first_group_expr = _resolve_alias_in_group_by(first_group_expr, aliases, context)
    return _is_to_start_of_day_timestamp(first_group_expr, context)


def _has_unsupported_clauses(node: ast.SelectQuery) -> bool:
    """Clauses the transform cannot preserve when rewriting to the preaggregated table."""
    return bool(
        node.having
        or node.window_exprs
        or node.prewhere
        or node.array_join_list
        or node.distinct
        or node.limit_by
        or node.limit_with_ties
    )


def _is_daily_unique_persons_pageviews_query(node: ast.SelectQuery, context: HogQLContext) -> bool:
    """
    Detect if a query matches the pattern:
    SELECT uniqExact(person_id) FROM events WHERE event='$pageview' GROUP BY toStartOfDay(timestamp)
    """
    # 1. Must select from 'events' table (no joins, SAMPLE 1 allowed)
    if not _is_valid_events_from(node.select_from):
        return False

    # 2. SELECT must be uniqExact(person_id) with optional toStartOfDay(timestamp)
    if not _select_is_uniq_persons_daily(node, context):
        return False

    # 3. WHERE must contain event='$pageview' filter and a timestamp range
    where_exprs = _flatten_and(node.where)
    if not any(_is_pageview_filter(expr) for expr in where_exprs):
        return False
    if _extract_timestamp_range(where_exprs, context) is None:
        return False

    # 4. GROUP BY must start with toStartOfDay(timestamp); more expressions allowed for breakdowns
    if not _group_by_starts_with_day(node, context):
        return False

    # 5. No unsupported clauses
    return not _has_unsupported_clauses(node)


def _build_insert_select_query(node: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """
    Build an INSERT SELECT query from the matched query pattern.

    Transforms:
        SELECT uniqExact(person_id) FROM events
        WHERE event='$pageview' AND timestamp >= '...'
        GROUP BY toStartOfDay(timestamp), properties.$browser

    Into:
        SELECT
            team_id,
            {job_id} AS job_id,  -- placeholder, filled by executor
            toStartOfDay(timestamp) AS time_window_start,
            [toString(properties.$browser), ...] AS breakdown_value,
            uniqExactState(person_id) AS uniq_exact_state
        FROM events
        WHERE event='$pageview'
        GROUP BY time_window_start, breakdown_value

    The timestamp filters are removed since they'll be added per-day by the executor.
    Column order matches the preaggregation_results table schema.
    """
    # 1. Build SELECT columns for the core transformation.
    #    The executor will prepend team_id and job_id when building the final INSERT.
    #    Output order: (time_window_start, breakdown_value, uniq_exact_state)

    # toStartOfDay(timestamp) AS time_window_start
    time_window_start = ast.Alias(
        alias="time_window_start",
        expr=ast.Call(name="toStartOfDay", args=[ast.Field(chain=["timestamp"])]),
    )

    # Build breakdown_value array from additional GROUP BY expressions
    breakdown_exprs: list[ast.Expr] = []
    if node.group_by and len(node.group_by) > 1:
        for group_expr in node.group_by[1:]:
            # Unwrap alias to get the actual expression
            expr = _unwrap_alias(group_expr)
            # Wrap in toString() to ensure string type for the array
            breakdown_exprs.append(ast.Call(name="toString", args=[expr]))

    # Create the breakdown_value column (array of breakdown dimensions)
    breakdown_value = ast.Alias(
        alias="breakdown_value",
        expr=ast.Array(exprs=breakdown_exprs) if breakdown_exprs else ast.Array(exprs=[]),
    )

    # uniqExactState(person_id) AS uniq_exact_state
    uniq_exact_state = ast.Alias(
        alias="uniq_exact_state",
        expr=ast.Call(name="uniqExactState", args=[ast.Field(chain=["person_id"])]),
    )

    # Core columns (executor will prepend team_id, job_id)
    select_columns: list[ast.Expr] = [time_window_start, breakdown_value, uniq_exact_state]

    # 2. Build WHERE clause - keep event filter, remove timestamp filters
    #    (they are re-added per-day by the executor)
    where_exprs = _flatten_and(node.where)
    non_timestamp_filters = [expr for expr in where_exprs if not _is_timestamp_filter(expr, context)]
    where_clause = _combine_and(non_timestamp_filters)

    # 3. Build GROUP BY - time_window_start + breakdown_value (if present)
    group_by_columns: list[ast.Expr] = [ast.Field(chain=["time_window_start"])]
    if breakdown_exprs:
        group_by_columns.append(ast.Field(chain=["breakdown_value"]))

    # 4. Construct the final SELECT query
    return ast.SelectQuery(
        select=select_columns,
        select_from=node.select_from,  # Keep the original FROM (events table)
        where=where_clause,
        group_by=group_by_columns,
    )


def _run_daily_unique_persons_pageviews(
    team: Team,
    query_to_insert: ast.SelectQuery,
    start: datetime,
    end: datetime,
) -> LazyComputationResult:
    """
    Orchestrate lazy computation jobs for daily unique persons pageviews.

    This function:
    1. Creates a LazyComputationQuery object from the query
    2. Calls the executor to find/create lazy computation jobs
    3. Returns the result with job IDs for the combiner query
    """
    query_info = LazyComputationQuery(
        query=query_to_insert, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone=team.timezone
    )

    executor = LazyComputationExecutor()
    result = executor.execute(
        team=team,
        query_info=query_info,
        start=start,
        end=end,
    )

    return result


def _build_lazy_select(node: ast.SelectQuery, context: HogQLContext) -> list[ast.Expr]:
    """Rewrite each SELECT expression to read from the preaggregated table."""
    select: list[ast.Expr] = []
    for orig_select in node.select:
        expr = _unwrap_alias(orig_select)
        orig_alias = orig_select.alias if isinstance(orig_select, ast.Alias) else None

        if _is_uniq_exact_persons_call(expr):
            # uniqExact(person_id) -> uniqExactMerge(uniq_exact_state)
            transformed_expr: ast.Expr = ast.Call(name="uniqExactMerge", args=[ast.Field(chain=["uniq_exact_state"])])
        elif _is_to_start_of_day_timestamp(expr, context):
            # toStartOfDay(timestamp) -> time_window_start
            transformed_expr = ast.Field(chain=["time_window_start"])
        else:
            # Shouldn't happen if pattern detection worked, but defensive
            continue

        select.append(ast.Alias(alias=orig_alias, expr=transformed_expr) if orig_alias else transformed_expr)
    return select


def _build_lazy_where(start_dt: datetime, end_dt: datetime, job_ids: list[uuid.UUID]) -> ast.Expr:
    """Build the WHERE clause bounding the day window and restricting to the computed jobs."""
    # Include the end day when the bound sits at end-of-day (23:59), so use < (end_date + 1 day).
    end_date_for_query = end_dt.date()
    if end_dt.hour == 23 and end_dt.minute == 59:
        end_date_for_query = end_date_for_query + timedelta(days=1)

    return ast.And(
        exprs=[
            ast.CompareOperation(
                left=ast.Field(chain=["time_window_start"]),
                right=ast.Constant(value=start_dt.date()),
                op=CompareOperationOp.GtEq,
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["time_window_start"]),
                right=ast.Constant(value=end_date_for_query),
                op=CompareOperationOp.Lt,
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["job_id"]),
                right=ast.Constant(value=job_ids),
                op=CompareOperationOp.In,
            ),
        ]
    )


def _build_lazy_group_by(node: ast.SelectQuery) -> list[ast.Expr]:
    """Map GROUP BY to time_window_start plus breakdown_value array elements (1-indexed)."""
    group_by: list[ast.Expr] = [ast.Field(chain=["time_window_start"])]
    if not node.group_by or len(node.group_by) <= 1:
        return group_by

    for idx, group_expr in enumerate(node.group_by[1:], start=1):
        original_alias = group_expr.alias if isinstance(group_expr, ast.Alias) else None
        breakdown_ref = ast.Call(
            name="arrayElement", args=[ast.Field(chain=["breakdown_value"]), ast.Constant(value=idx)]
        )
        group_by.append(ast.Alias(alias=original_alias, expr=breakdown_ref) if original_alias else breakdown_ref)
    return group_by


class Transformer(CloningVisitor):
    """Transform queries to use daily_unique_persons_pageviews table."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # First, recursively transform any nested select queries (e.g., subqueries, CTEs)
        transformed_node = super().visit_select_query(node)

        # Check if this query matches the pattern
        if not _is_daily_unique_persons_pageviews_query(transformed_node, self.context):
            return transformed_node

        # Extract date range
        where_exprs = _flatten_and(transformed_node.where)
        timestamp_range = _extract_timestamp_range(where_exprs, self.context)

        if not timestamp_range:
            # Shouldn't happen if pattern detection worked, but defensive
            return transformed_node

        start_dt, end_dt = timestamp_range

        # Build the INSERT SELECT query from the matched query
        query_to_insert = _build_insert_select_query(transformed_node, self.context)

        # Run the lazy computation job orchestration
        team = self.context.team
        if not team:
            return transformed_node
        result = _run_daily_unique_persons_pageviews(team, query_to_insert, start_dt, end_dt)

        if not result.ready:
            # Lazy computation not ready, fall back to original query
            return transformed_node

        # FROM preaggregation_results (HogQL name, maps to sharded_preaggregation_results in ClickHouse)
        select_from = ast.JoinExpr(
            table=ast.Field(chain=["preaggregation_results"]),
            alias=transformed_node.select_from.alias if transformed_node.select_from else None,
            constraint=None,
            next_join=None,
            sample=None,
        )

        # Create transformed query
        final_transformed = ast.SelectQuery(
            select=_build_lazy_select(transformed_node, self.context),
            select_from=select_from,
            group_by=_build_lazy_group_by(transformed_node),
            where=_build_lazy_where(start_dt, end_dt, result.job_ids),
            array_join_list=None,
            array_join_op=None,
            limit_by=None,
            limit_with_ties=None,
            window_exprs=None,
            prewhere=None,
            view_name=None,
            distinct=None,
            limit=transformed_node.limit,
            offset=transformed_node.offset,
            order_by=transformed_node.order_by,
            having=transformed_node.having,
            settings=transformed_node.settings,
            ctes=transformed_node.ctes,  # Preserve CTEs, they should get transformed by the outer visitor
        )
        return final_transformed
