import random
import string
from collections.abc import Callable
from datetime import datetime
from typing import Optional, cast

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, LazyJoin, LazyJoinToAdd, LazyTableToAdd
from posthog.hogql.database.schema.util.uuid import (
    uuid_uint128_expr_to_timestamp_expr_v2,
    uuid_uint128_expr_to_timestamp_expr_v3,
)
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.helpers.timestamp_visitor import is_simple_timestamp_field_expression, is_time_or_interval_constant
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

SESSION_BUFFER_DAYS = 3
DEFAULT_SESSION_LOOKBACK_DAYS = 30
DEFAULT_SESSION_LOOKBACK_CACHE_TTL_SECONDS = 60


class WhereClauseExtractor(CloningVisitor):
    """This class extracts reductive filters from the Where clause into a lazily joined table.

    This class is called on the select query of the lazy table, and will return the where clause that should be applied to
    the inner table.

    As a query can be unreasonably complex, we only handle simple cases, but this class is designed to fail-safe. If it
    can't reason about a particular expression, it will just return a constant True, i.e. fetch more rows than necessary.

    This means that we can incrementally add support for more complex queries, without breaking existing queries, by
    handling more cases.

    Some examples of failing-safe:

    `SELECT * FROM sessions where min_timestamp > '2022-01-01' AND f(session_id)`
    only the` min_timestamp > '2022-01-01'` part is relevant, so we can ignore the `f(session_id)` part, and it is safe
    to replace it with a constant True, which collapses the AND to just the `min_timestamp > '2022-01-01'` part.

    `SELECT * FROM sessions where min_timestamp > '2022-01-01' OR f(session_id)`
    only the` min_timestamp > '2022-01-01'` part is relevant, and turning the `f(session_id)` part into a constant True
    would collapse the OR to True. In this case we return None as no pre-filtering is possible.

    All min_timestamp comparisons are given a buffer of SESSION_BUFFER_DAYS each side, to ensure that we collect all the
    relevant rows for each session.
    """

    context: HogQLContext
    clear_types: bool = False
    clear_locations: bool = False
    capture_timestamp_comparisons: bool = False  # implement handle_timestamp_comparison if setting this to True
    is_join: bool = False
    tracked_tables: list[ast.LazyTable | ast.LazyJoin]
    tombstone_string: str

    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.tracked_tables = []
        # A constant with this string will be used to escape early if we can't handle the query
        self.tombstone_string = (
            "__TOMBSTONE__" + ("".join(random.choices(string.ascii_uppercase + string.digits, k=10))) + "__"
        )

    def handle_timestamp_comparison(
        self, node: ast.CompareOperation, is_left_constant: bool, is_right_constant: bool
    ) -> Optional[ast.Expr]:
        raise NotImplementedError(
            message=f"handle_timestamp_comparison not implemented"
        )  # handle this in a subclass if setting capture_timestamp_comparisons to True

    def add_local_tables(self, join_or_table: LazyJoinToAdd | LazyTableToAdd):
        """Add the tables whose filters to extract into a new where clause."""
        if isinstance(join_or_table, LazyJoinToAdd):
            if join_or_table.lazy_join not in self.tracked_tables:
                self.tracked_tables.append(join_or_table.lazy_join)
        elif isinstance(join_or_table, LazyTableToAdd):
            if join_or_table.lazy_table not in self.tracked_tables:
                self.tracked_tables.append(join_or_table.lazy_table)

    def get_inner_where(self, select_query: ast.SelectQuery) -> Optional[ast.Expr]:
        """Return the where clause that should be applied to the inner table. If None is returned, no pre-filtering is possible."""
        if not select_query.where and not select_query.prewhere:
            return None

        if select_query.select_from and select_query.select_from.next_join:
            self.is_join = True

        # visit the where clause
        wheres = []
        if select_query.where:
            wheres.append(select_query.where)
        if select_query.prewhere:
            wheres.append(select_query.prewhere)

        if len(wheres) == 1:
            where = self.visit(wheres[0])
        else:
            where = self.visit(ast.And(exprs=wheres))

        if isinstance(where, ast.Constant):
            return None

        return clone_expr(where, clear_types=True, clear_locations=True)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        if has_tombstone(node, self.tombstone_string):
            return ast.Constant(value=self.tombstone_string)

        is_left_constant = is_time_or_interval_constant(node.left, self.tombstone_string)
        is_right_constant = is_time_or_interval_constant(node.right, self.tombstone_string)

        # just ignore constant comparison
        if is_left_constant and is_right_constant:
            return ast.Constant(value=True)

        # extract timestamps from the main query into e.g. the sessions subquery
        if self.capture_timestamp_comparisons:
            result = self.handle_timestamp_comparison(node, is_left_constant, is_right_constant)
            if result:
                return result

        # if it's a join, and if the comparison is negative, we don't want to filter down as the outer join might end up doing other comparisons that clash
        if self.is_join and node.op in ast.NEGATED_COMPARE_OPS:
            return ast.Constant(value=True)

        # Check if any of the fields are a field on our requested table
        if len(self.tracked_tables) > 0:
            left = self.visit(node.left)

            if isinstance(node.right, ast.SelectQuery):
                right = clone_expr(
                    node.right, clear_types=False, clear_locations=False, inline_subquery_field_names=True
                )
            else:
                right = self.visit(node.right)

            if has_tombstone(left, self.tombstone_string) or has_tombstone(right, self.tombstone_string):
                return ast.Constant(value=self.tombstone_string)
            return ast.CompareOperation(op=node.op, left=left, right=right)

        return ast.Constant(value=True)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        # don't even try to handle complex logic
        return ast.Constant(value=True)

    def visit_not(self, node: ast.Not) -> ast.Expr:
        if self.is_join:
            return ast.Constant(value=True)
        response = self.visit(node.expr)
        if has_tombstone(response, self.tombstone_string):
            return ast.Constant(value=self.tombstone_string)
        return ast.Not(expr=response)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name == "and":
            return self.visit_and(ast.And(exprs=node.args))
        elif node.name == "or":
            return self.visit_or(ast.Or(exprs=node.args))
        elif node.name == "not":
            if self.is_join:
                return ast.Constant(value=True)

        elif node.name in HOGQL_COMPARISON_MAPPING:
            op = HOGQL_COMPARISON_MAPPING[node.name]
            if len(node.args) != 2:
                raise QueryError(f"Comparison '{node.name}' requires exactly two arguments")
            # We do "cleverer" logic with nullable types in visit_compare_operation
            return self.visit_compare_operation(
                ast.CompareOperation(
                    left=node.args[0],
                    right=node.args[1],
                    op=op,
                )
            )
        args = [self.visit(arg) for arg in node.args]
        if any(has_tombstone(arg, self.tombstone_string) for arg in args):
            return ast.Constant(value=self.tombstone_string)
        return ast.Call(name=node.name, args=args)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        # if field in requested list
        type = node.type
        if isinstance(type, ast.PropertyType):
            type = type.field_type
        if isinstance(type, ast.FieldAliasType):
            type = type.type
        if isinstance(type, ast.FieldType):
            table_type = type.table_type
            if (isinstance(table_type, ast.LazyTableType) and table_type.table in self.tracked_tables) or (
                isinstance(table_type, ast.LazyJoinType) and table_type.lazy_join in self.tracked_tables
            ):
                new_field = cast(ast.Field, clone_expr(node))
                if isinstance(node.type, ast.PropertyType):
                    chain_length = len(node.type.chain) + 1
                else:
                    chain_length = 1
                new_field.chain = new_field.chain[-chain_length:]
                return new_field
        return ast.Constant(value=self.tombstone_string)

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        return ast.Constant(value=node.value)

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        raise Exception()  # this should never happen, as placeholders should be resolved before this runs

    def visit_and(self, node: ast.And) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]
        flattened = flatten_ands(exprs)

        filtered = []
        for expr in flattened:
            if isinstance(expr, ast.Constant):
                if is_not_truthy(expr.value):
                    return ast.Constant(value=False)
                # skip all tombstones
            else:
                filtered.append(expr)

        if len(filtered) == 0:
            return ast.Constant(value=True)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.And(exprs=filtered)

    def visit_or(self, node: ast.Or) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]
        flattened = flatten_ors(exprs)

        filtered = []
        for expr in flattened:
            if has_tombstone(expr, self.tombstone_string):
                return ast.Constant(value=self.tombstone_string)
            if isinstance(expr, ast.Constant):
                if is_truthy(expr.value):
                    return ast.Constant(value=True)
            else:
                filtered.append(expr)

        if len(filtered) == 0:
            return ast.Constant(value=False)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.Or(exprs=filtered)

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


class SessionMinTimestampWhereClauseExtractor(WhereClauseExtractor):
    capture_timestamp_comparisons = True
    timestamp_field: ast.Expr
    time_buffer: ast.Expr

    def __init__(self, context: HogQLContext):
        super().__init__(context)

    def should_apply_default_limit_bound(self, select_query: ast.SelectQuery) -> bool:
        if (
            select_query.limit is None
            or select_query.order_by
            or select_query.where is not None
            or select_query.prewhere is not None
        ):
            return False
        if len(select_query.select) != 1:
            return False
        selected = select_query.select[0]
        return isinstance(selected, ast.Field) and selected.chain == ["*"]

    def get_default_limit_bound(self) -> ast.Expr:
        team_id = self.context.team_id
        if team_id is None:
            return ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Sub,
                left=ast.Call(name="now", args=[]),
                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=DEFAULT_SESSION_LOOKBACK_DAYS)]),
            )

        cache_key = f"sessions_default_limit_bound:last_seen_at:{team_id}"
        cache_miss = object()
        cached_last_seen_at = cache.get(cache_key, cache_miss)
        if cached_last_seen_at is cache_miss:
            from products.event_definitions.backend.models.event_definition import EventDefinition

            latest_event_last_seen_at = (
                EventDefinition.objects.filter(team_id=team_id, last_seen_at__isnull=False)
                .values_list("last_seen_at", flat=True)
                .order_by("-last_seen_at")
                .first()
            )
            cache.set(cache_key, latest_event_last_seen_at, timeout=DEFAULT_SESSION_LOOKBACK_CACHE_TTL_SECONDS)
        else:
            latest_event_last_seen_at = cast(Optional[datetime], cached_last_seen_at)

        if latest_event_last_seen_at is None:
            reference_time: ast.Expr = ast.Call(name="now", args=[])
        else:
            reference_time = ast.Call(
                name="toDateTime",
                args=[ast.Constant(value=latest_event_last_seen_at.strftime("%Y-%m-%d %H:%M:%S"))],
            )

        return ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Sub,
            left=reference_time,
            right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=DEFAULT_SESSION_LOOKBACK_DAYS)]),
        )

    def get_inner_where(self, select_query: ast.SelectQuery) -> Optional[ast.Expr]:
        result = super().get_inner_where(select_query)
        if result is not None:
            return result
        if self.should_apply_default_limit_bound(select_query):
            return ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=clone_expr(self.timestamp_field),
                right=self.get_default_limit_bound(),
            )
        return None

    def handle_timestamp_comparison(
        self, node: ast.CompareOperation, is_left_constant: bool, is_right_constant: bool
    ) -> Optional[ast.Expr]:
        is_left_timestamp_field = is_simple_timestamp_field_expression(node.left, self.context, self.tombstone_string)
        is_right_timestamp_field = is_simple_timestamp_field_expression(node.right, self.context, self.tombstone_string)

        # handle the left side being a min_timestamp expression and the right being constant
        if is_left_timestamp_field and is_right_constant:
            if node.op == CompareOperationOp.Eq:
                return ast.And(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                            right=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Sub,
                                left=node.right,
                                right=self.time_buffer,
                            ),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                            right=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Add,
                                left=node.right,
                                right=self.time_buffer,
                            ),
                        ),
                    ]
                )
            elif node.op == CompareOperationOp.Gt or node.op == CompareOperationOp.GtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                    right=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Sub,
                        left=node.right,
                        right=self.time_buffer,
                    ),
                )
            elif node.op == CompareOperationOp.Lt or node.op == CompareOperationOp.LtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=rewrite_timestamp_field(node.left, self.timestamp_field, self.context),
                    right=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=node.right,
                        right=self.time_buffer,
                    ),
                )
        elif is_right_timestamp_field and is_left_constant:
            # let's not duplicate the logic above, instead just flip and it and recurse
            if node.op in [
                CompareOperationOp.Eq,
                CompareOperationOp.Lt,
                CompareOperationOp.LtEq,
                CompareOperationOp.Gt,
                CompareOperationOp.GtEq,
            ]:
                return self.visit(
                    ast.CompareOperation(
                        op=CompareOperationOp.Eq
                        if node.op == CompareOperationOp.Eq
                        else CompareOperationOp.Lt
                        if node.op == CompareOperationOp.Gt
                        else CompareOperationOp.LtEq
                        if node.op == CompareOperationOp.GtEq
                        else CompareOperationOp.Gt
                        if node.op == CompareOperationOp.Lt
                        else CompareOperationOp.GtEq,
                        left=node.right,
                        right=node.left,
                    )
                )

        if node.op == CompareOperationOp.Eq:
            if is_left_constant and is_session_id_string_expr(node.right, self.context):
                left_timestamp_expr = self.session_id_str_to_timestamp_expr(node.left)
                if left_timestamp_expr is None:
                    return None
                return ast.CompareOperation(
                    op=CompareOperationOp.Eq, left=left_timestamp_expr, right=self.timestamp_field
                )
            elif is_right_constant and is_session_id_string_expr(node.left, self.context):
                right_timestamp_expr = self.session_id_str_to_timestamp_expr(node.right)
                if right_timestamp_expr is None:
                    return None
                return ast.CompareOperation(
                    op=CompareOperationOp.Eq, left=self.timestamp_field, right=right_timestamp_expr
                )

        return None

    def session_id_str_to_timestamp_expr(self, session_id_str_expr: ast.Expr) -> Optional[ast.Expr]:
        return None


class SessionMinTimestampWhereClauseExtractorV1(SessionMinTimestampWhereClauseExtractor):
    timestamp_field = ast.Field(chain=["raw_sessions", "min_timestamp"])
    time_buffer = ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)])


class SessionMinTimestampWhereClauseExtractorV2(SessionMinTimestampWhereClauseExtractor):
    timestamp_field = uuid_uint128_expr_to_timestamp_expr_v2(ast.Field(chain=["raw_sessions", "session_id_v7"]))
    time_buffer = ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)])


class SessionMinTimestampWhereClauseExtractorV3(SessionMinTimestampWhereClauseExtractor):
    timestamp_field = ast.Field(chain=["raw_sessions_v3", "session_timestamp"])
    time_buffer = ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)])

    def session_id_str_to_timestamp_expr(self, session_id_str_expr: ast.Expr) -> Optional[ast.Expr]:
        # this is a roundabout way of doing it, but we want to match the logic in the clickhouse table definition
        timestamp_expr = uuid_uint128_expr_to_timestamp_expr_v3(
            ast.Call(name="_toUInt128", args=[ast.Call(name="toUUID", args=[session_id_str_expr])])
        )
        return timestamp_expr


class EventsOnlyWhereClauseExtractor(WhereClauseExtractor):
    """Extract predicates from the outer WHERE that only reference the events table.

    Used to build a ``session_id_v7 IN (SELECT $session_id_uuid FROM events WHERE <events-only>)``
    pushdown into the raw_sessions subquery, so aggregation state only covers sessions that
    actually participate in the outer events filter.

    **This is a targeted fix for one customer's ExperimentQuery OOMs, not a general-purpose
    optimization.** Benchmarks in the analysis doc show the pushdown *regresses* most other
    traffic — e.g. a healthy ``WebStatsTableQuery`` got +93% runtime / +32% memory once the
    pushdown kicked in, because a ``$pageview OR $screen`` filter doesn't narrow the session
    set and the ``GLOBAL IN`` broadcast + double events scan dominate. The modifier that
    activates this code path (``sessionIdPushdown``) is therefore off by default and is only
    turned on by ``ExperimentQueryRunner``, gated by a per-team feature flag so we can enable
    it for the single affected team without touching anyone else.

    Background, numbers, and the rollout decision:
    https://github.com/PostHog/query-performance-analysis/blob/main/analysis/2026-04-17-experiment-sessions-oom.md

    Inverts the field-tracking semantics of ``WhereClauseExtractor``: we keep fields that
    resolve to the EventsTable and tombstone everything else, letting the base AND/OR/NOT
    logic drop unsafe branches.

    When ``session_lazy_join`` is set, an extra narrowing step drops OR disjuncts that
    don't reference the session join. Rows matching those dropped disjuncts don't consult
    ``events__session.*`` columns, so their LEFT JOIN producing NULL is semantically
    equivalent to their original behavior — keeping them in the IN subquery just inflates
    the session set without narrowing. See the 2026-04-17 analysis doc for the follow-up
    benchmark showing 4.5× speedup on rare-step-1 funnels.
    """

    session_lazy_join: Optional[LazyJoin] = None

    def __init__(self, context: HogQLContext, session_lazy_join: Optional[LazyJoin] = None):
        super().__init__(context)
        self.session_lazy_join = session_lazy_join

    def visit_or(self, node: ast.Or) -> ast.Expr:
        if self.session_lazy_join is not None:
            # Flatten nested ORs so narrowing is based on leaf disjuncts, then keep
            # only those that reference the session lazy join.
            flattened = flatten_ors(node.exprs)
            kept = [expr for expr in flattened if _expr_references_lazy_join(expr, self.session_lazy_join)]
            if kept and len(kept) < len(flattened):
                if len(kept) == 1:
                    return self.visit(kept[0])
                return super().visit_or(ast.Or(exprs=kept))
        return super().visit_or(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        if has_tombstone(node, self.tombstone_string):
            return ast.Constant(value=self.tombstone_string)

        is_left_constant = is_time_or_interval_constant(node.left, self.tombstone_string)
        is_right_constant = is_time_or_interval_constant(node.right, self.tombstone_string)
        if is_left_constant and is_right_constant:
            return ast.Constant(value=True)

        left = self.visit(node.left)
        if isinstance(node.right, ast.SelectQuery):
            right = clone_expr(node.right, clear_types=False, clear_locations=False, inline_subquery_field_names=True)
        else:
            right = self.visit(node.right)

        if has_tombstone(left, self.tombstone_string) or has_tombstone(right, self.tombstone_string):
            return ast.Constant(value=self.tombstone_string)
        return ast.CompareOperation(op=node.op, left=left, right=right)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if is_events_only_field(node):
            return cast(ast.Field, clone_expr(node))
        return ast.Constant(value=self.tombstone_string)


def _expr_references_lazy_join(expr: ast.Expr, lazy_join: LazyJoin) -> bool:
    """True iff ``expr`` contains any field whose resolved type traverses ``lazy_join``."""
    visitor = _ReferencesLazyJoinVisitor(lazy_join)
    visitor.visit(expr)
    return visitor.found


class _ReferencesLazyJoinVisitor(TraversingVisitor):
    found: bool = False
    lazy_join: LazyJoin

    def __init__(self, lazy_join: LazyJoin):
        self.lazy_join = lazy_join

    def visit_field(self, node: ast.Field):
        if self.found:
            return
        type_ = node.type
        if isinstance(type_, ast.PropertyType):
            type_ = type_.field_type
        if isinstance(type_, ast.FieldAliasType):
            type_ = type_.type
        if not isinstance(type_, ast.FieldType):
            return
        table_type = type_.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if isinstance(table_type, ast.LazyJoinType) and table_type.lazy_join is self.lazy_join:
            self.found = True


def is_events_only_field(node: ast.Field) -> bool:
    """True iff the field resolves to a direct field on the EventsTable (not a traversal to
    person/groups/sessions/etc. via a virtual/lazy join)."""
    from posthog.hogql.database.schema.events import EventsTable

    type_ = node.type
    if isinstance(type_, ast.PropertyType):
        type_ = type_.field_type
    if isinstance(type_, ast.FieldAliasType):
        type_ = type_.type
    if not isinstance(type_, ast.FieldType):
        return False

    table_type = type_.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        table_type = table_type.table_type
    # Virtual tables (e.g. person, group) pivot to another underlying table, so they are not
    # safely "events-only" even if they hang off an events row.

    if isinstance(table_type, ast.TableType):
        return isinstance(table_type.table, EventsTable)
    return False


def build_session_id_v7_pushdown_predicate(
    outer_node: ast.SelectQuery,
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    session_id_v7_field: ast.Expr,
    events_session_id_field: list[str | int],
) -> Optional[ast.Expr]:
    """Build ``raw_sessions.session_id_v7 IN (SELECT DISTINCT events.<session_id_field>
    FROM events WHERE <events-only WHERE of outer query>)``.

    Returns None if the outer query shape or WHERE can't be safely pushed down.
    """
    events_join = _find_join_for_alias(outer_node.select_from, join_to_add.from_table)
    if events_join is None or not isinstance(events_join.table, ast.Field):
        return None

    events_where = EventsOnlyWhereClauseExtractor(context, session_lazy_join=join_to_add.lazy_join).get_inner_where(
        outer_node
    )
    if events_where is None:
        return None

    events_alias = join_to_add.from_table
    subquery = ast.SelectQuery(
        select=[ast.Field(chain=[events_alias, *events_session_id_field])],
        distinct=True,
        select_from=ast.JoinExpr(
            table=ast.Field(chain=list(events_join.table.chain)),
            alias=events_alias,
        ),
        where=events_where,
    )

    return ast.CompareOperation(
        op=CompareOperationOp.In,
        left=session_id_v7_field,
        right=subquery,
    )


def build_session_property_pre_aggregation_predicate(
    outer_node: ast.SelectQuery,
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    requested_fields: dict[str, list[str | int]],
    select_from_fn: Callable[[dict[str, list[str | int]], ast.SelectQuery, HogQLContext], ast.SelectQuery],
    session_id_v7_field: ast.Expr,
) -> Optional[ast.Expr]:
    """Build ``raw_sessions.session_id_v7 IN (SELECT session_id_v7 FROM <small inner> WHERE <session predicate>)``.

    The "small inner" is a recursive call to ``select_from_fn`` (the same builder) with a pruned
    ``requested_fields`` containing only the session aliases referenced by the predicate. That
    keeps the small inner's GROUP BY hash table cheap — one or two AggregateFunction states per
    session instead of however many the outer SELECT pulls in (e.g. ``$channel_type`` drags in
    7+).

    Returns None when ``WhereClauseExtractor`` produces no liftable session predicate (no session
    filter, or only filters guarded by NOT/OR with non-session terms — see the visitor's tombstone
    handling). The predicate-references-outer-fields check is a defensive belt; in practice
    ``requested_fields`` already contains every session alias the outer query references, so
    extraction guarantees a non-empty intersection.
    """
    extractor = WhereClauseExtractor(context)
    extractor.add_local_tables(join_to_add)
    lifted = extractor.get_inner_where(outer_node)
    if lifted is None or isinstance(lifted, ast.Constant):
        return None

    referenced_aliases = _collect_referenced_top_level_aliases(lifted)
    referenced_in_outer = referenced_aliases & {name for name in requested_fields if name != "session_id_v7"}
    if not referenced_in_outer:
        return None

    pruned_fields: dict[str, list[str | int]] = {name: requested_fields[name] for name in referenced_in_outer}
    pruned_fields["session_id_v7"] = ["session_id_v7"]

    small_inner = select_from_fn(pruned_fields, outer_node, context)

    wrapped = ast.SelectQuery(
        select=[ast.Field(chain=["session_id_v7"])],
        select_from=ast.JoinExpr(table=small_inner),
        where=lifted,
    )

    return ast.CompareOperation(
        op=CompareOperationOp.In,
        left=session_id_v7_field,
        right=wrapped,
    )


def _collect_referenced_top_level_aliases(expr: ast.Expr) -> set[str]:
    visitor = _CollectTopLevelAliasesVisitor()
    visitor.visit(expr)
    return visitor.names


class _CollectTopLevelAliasesVisitor(TraversingVisitor):
    names: set[str]

    def __init__(self):
        self.names = set()

    def visit_field(self, node: ast.Field):
        if node.chain:
            self.names.add(str(node.chain[0]))


def _find_join_for_alias(select_from: Optional[ast.JoinExpr], alias: str) -> Optional[ast.JoinExpr]:
    ptr = select_from
    while ptr:
        current_alias = ptr.alias
        if current_alias is None and isinstance(ptr.table, ast.Field) and ptr.table.chain:
            current_alias = str(ptr.table.chain[0])
        if current_alias == alias:
            return ptr
        ptr = ptr.next_join
    return None


def has_tombstone(expr: ast.Expr, tombstone_string: str) -> bool:
    visitor = HasTombstoneVisitor(tombstone_string)
    visitor.visit(expr)
    return visitor.has_tombstone


class HasTombstoneVisitor(TraversingVisitor):
    has_tombstone = False
    tombstone_string: str

    def __init__(self, tombstone_string: str):
        self.tombstone_string = tombstone_string

    def visit_constant(self, node: ast.Constant):
        if node.value == self.tombstone_string:
            self.has_tombstone = True


def rewrite_timestamp_field(expr: ast.Expr, timestamp_field: ast.Expr, context: HogQLContext) -> ast.Expr:
    return RewriteTimestampFieldVisitor(context, timestamp_field).visit(expr)


class RewriteTimestampFieldVisitor(CloningVisitor):
    context: HogQLContext
    timestamp_field: ast.Expr

    def __init__(self, context: HogQLContext, timestamp_field: ast.Expr, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context
        self.timestamp_field = timestamp_field

    def visit_field(self, node: ast.Field) -> ast.Expr:
        from posthog.hogql.database.schema.events import EventsTable
        from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable
        from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
        from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
        from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3

        if node.type and isinstance(node.type, ast.FieldType):
            resolved_field = node.type.resolve_database_field(self.context)
            table_type = node.type.resolve_table_type(self.context)
            if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                table_type = table_type.table_type
            # Get the underlying table based on the table_type
            table = None
            if isinstance(table_type, ast.LazyJoinType):
                table = table_type.lazy_join.join_table
            elif isinstance(table_type, ast.SelectQueryAliasType):
                pass  # Subquery aliases don't represent actual database tables
            elif hasattr(table_type, "table"):
                table = table_type.table
            if table is not None and resolved_field and isinstance(resolved_field, DatabaseField):
                if (
                    (isinstance(table, EventsTable) and resolved_field.name == "timestamp")
                    or (
                        isinstance(table, SessionsTableV1)
                        and resolved_field.name in ("$start_timestamp", "$end_timestamp")
                    )
                    or (
                        isinstance(table, SessionsTableV2)
                        and resolved_field.name in ("$start_timestamp", "$end_timestamp")
                    )
                    or (
                        isinstance(table, SessionsTableV3)
                        and resolved_field.name in ("$start_timestamp", "$end_timestamp")
                    )
                    or (isinstance(table, RawSessionReplayEventsTable) and resolved_field.name == "min_first_timestamp")
                ):
                    return self.timestamp_field
        # no type information, so just use the name of the field
        if node.chain[-1] in [
            "$start_timestamp",
            "$end_timestamp",
            "min_timestamp",
            "timestamp",
            "min_first_timestamp",
        ]:
            return self.timestamp_field
        return node

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def is_session_id_string_expr(node: ast.Expr, context: HogQLContext) -> bool:
    if isinstance(node, ast.Field):
        from posthog.hogql.database.schema.events import EventsTable
        from posthog.hogql.database.schema.session_replay_events import RawSessionReplayEventsTable
        from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3

        if node.type and isinstance(node.type, ast.FieldType):
            resolved_field = node.type.resolve_database_field(context)
            table_type = node.type.resolve_table_type(context)
            if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                table_type = table_type.table_type
            if isinstance(table_type, ast.LazyJoinType):
                table = table_type.lazy_join.join_table
            elif isinstance(table_type, ast.SelectQueryAliasType):
                # Subquery aliases don't represent actual database tables
                return False
            elif hasattr(table_type, "table"):
                table = table_type.table
            else:
                return False
            if resolved_field and isinstance(resolved_field, DatabaseField):
                if (
                    (isinstance(table, EventsTable) and resolved_field.name == "$session_id")
                    or (isinstance(table, SessionsTableV3) and resolved_field.name in ("session_id"))
                    or (isinstance(table, RawSessionReplayEventsTable) and resolved_field.name == "min_first_timestamp")
                ):
                    return True
        # no type information, so just use the name of the field
        if node.chain[-1] in [
            "session_id",
            "$session_id",
        ]:
            return True
    if isinstance(node, ast.Alias):
        return is_session_id_string_expr(node.expr, context)
    return False


def flatten_ands(exprs):
    flattened = []
    for expr in exprs:
        if isinstance(expr, ast.And):
            flattened.extend(flatten_ands(expr.exprs))
        else:
            flattened.append(expr)
    return flattened


def flatten_ors(exprs):
    flattened = []
    for expr in exprs:
        if isinstance(expr, ast.Or):
            flattened.extend(flatten_ors(expr.exprs))
        else:
            flattened.append(expr)
    return flattened


def is_not_truthy(value):
    return value is False or value is None or value == 0


def is_truthy(value):
    return not is_not_truthy(value)
