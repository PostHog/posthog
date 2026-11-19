"""Aggregate inside each branch of the flag-calls union.

Lazy table resolution expands `posthog.events_with_flag_calls` to a subquery over a union of `events` and
`posthog.flag_evaluations` scans. ClickHouse runs a GROUP BY above a subquery of a Distributed table on the initiator,
so each shard sends every row it reads. This transform rewrites an aggregating query over that union:

    SELECT agg(x), k FROM (SELECT ... FROM (b1 UNION ALL b2)) AS e WHERE w GROUP BY k HAVING h ORDER BY o
    ->
    SELECT aggMerge(s), k' FROM (
        SELECT aggState(x1) AS s, k1 AS k' FROM events WHERE <b1 filter> AND w1 GROUP BY k'
        UNION ALL
        SELECT aggState(x2) AS s, k2 AS k' FROM flag_evaluations WHERE <b2 filter> AND w2 GROUP BY k'
    ) GROUP BY k' HAVING h' ORDER BY o'

`x1`, `k1` and `w1` read each union column as branch 1's own expression for it. Each branch reads its table directly,
because ClickHouse also keeps an aggregation on the initiator when a subquery sits between it and the table. Each
shard then sends partial aggregation states.

The rewrite runs after property resolution, when the union's branches are final. It applies only when the guards in
`_rewrite` show that the rewritten query returns the same rows. Any unexpected error leaves the query untouched.
"""

import dataclasses
from typing import cast

import structlog

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.compilation import compilation_budget
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events_with_flag_calls import union_scan
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.printer.clickhouse import call_column_name, printed_aliases
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import SyntaxVisitor, and_conditions, select_aliases
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

# Aggregates whose merged state equals the direct result whatever order the rows arrive in. Each one's state is the
# state of the same function. `sumIf` keeps the Nullable result that `sumStateIf` would drop. `count(DISTINCT x)`
# maps to `countDistinct`. `countState(DISTINCT x)` keeps no set of values, so it merges to a sum of counts.
_ORDER_INDEPENDENT_AGGREGATES = frozenset(
    {
        "count",
        "countIf",
        "countDistinct",
        "sum",
        "sumIf",
        "avg",
        "avgIf",
        "min",
        "minIf",
        "max",
        "maxIf",
        "uniq",
        "uniqIf",
        "uniqExact",
        "uniqExactIf",
    }
)

_RESERVED_PREFIX = "__flag_calls_"

# A chain of aliases that each read the previous one twice doubles the inlined expression at every step.
_MAX_ALIAS_EXPANSIONS = 1_000

_ROW_POSITION_FUNCTIONS = frozenset({"blocknumber", "rownumberinblock", "rownumberinallblocks", "neighbor"})


def preaggregate_flag_calls_union(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Rewrites, in place, each aggregating query over the flag-calls union to aggregate inside each branch."""
    _Preaggregator(context).visit(node)
    return node


def _state_column(index: int) -> str:
    return f"{_RESERVED_PREFIX}state_{index}"


def _key_column(index: int) -> str:
    return f"{_RESERVED_PREFIX}key_{index}"


class _Decline(Exception):
    pass


class _Preaggregator(SyntaxVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)
        if node.select_from is None:
            return
        scan = union_scan(node.select_from)
        if scan is None:
            return
        try:
            _rewrite(node, scan, self.context)
        except _Decline as decline:
            logger.debug("flag_calls_union_preaggregation_declined", reason=str(decline))
        except Exception as err:
            budget = compilation_budget.get()
            if budget is not None:
                budget.check_time()
            # _rewrite changes `node` only after every check passes. A failure therefore leaves it as it was.
            logger.warning("flag_calls_union_preaggregation_unexpected_error", error=str(err), exc_info=True)


@frozen
class _Branch:
    query: ast.SelectQuery
    columns: dict[str, ast.Expr]


@frozen
class _Aggregate:
    call: ast.Call
    function: str
    column: str

    @property
    def state(self) -> str:
        return f"{self.function}State"

    @property
    def merge(self) -> str:
        return f"{self.function}Merge"


@frozen
class _Plan:
    """What `_rewrite` builds before it changes the query."""

    scan_alias: str
    exported: dict[str, str]
    aliases: dict[str, ast.Expr]
    keys: list[ast.Expr]
    aggregates: dict[int, _Aggregate] = dataclasses.field(default_factory=dict)


def _rewrite(node: ast.SelectQuery, scan: ast.SelectQuery, context: HogQLContext) -> None:
    assert node.select_from is not None and isinstance(node.select_from.type, ast.SelectQueryAliasType)
    _check_query_shape(node)
    branches = _branches(scan)
    plan = _Plan(
        scan_alias=node.select_from.type.alias,
        exported={
            cast(ast.Alias, column).alias: str(cast(ast.Field, cast(ast.Alias, column).expr).chain[-1])
            for column in scan.select
        },
        aliases=_aliases(node),
        keys=[_group_by_expression(key, node) for key in node.group_by or []],
    )
    if any(alias.startswith(_RESERVED_PREFIX) for alias in plan.aliases):
        raise _Decline("alias_uses_a_generated_name")
    shapes = _Shapes(plan)
    checker = _ExpressionChecker(plan, shapes)
    for clause in _clauses(node):
        checker.visit(clause)

    key_aggregates = _AggregateCollector(shapes)
    for key in plan.keys:
        key_aggregates.visit(key)
    if key_aggregates.aggregates:
        # ClickHouse rejects an aggregate in GROUP BY. A generated key column would hide that rejection.
        raise _Decline("aggregate_in_group_by")

    collector = _AggregateCollector(shapes)
    for clause in [*node.select, *([node.having] if node.having else []), *(o.expr for o in node.order_by or [])]:
        collector.visit(clause)
    plan = dataclasses.replace(plan, aggregates=collector.aggregates)
    if not plan.aggregates and not plan.keys:
        raise _Decline("not_aggregating")

    _check_branch_types(node, plan, shapes, branches, context)

    branch_queries = [_branch_query(branch, node, plan) for branch in branches]
    set_type = ast.SelectSetQueryType(types=[cast(ast.SelectQueryType, query.type) for query in branch_queries])
    outer_rewriter = _OuterRewriter(plan, shapes, set_type)
    select = _rewrite_select(node.select, outer_rewriter, context)
    having = outer_rewriter.visit(node.having) if node.having is not None else None
    order_by = [
        ast.OrderExpr(expr=outer_rewriter.visit(order.expr), order=order.order) for order in node.order_by or []
    ] or None
    group_by: list[ast.Expr] | None = [outer_rewriter.key_field(index) for index in range(len(plan.keys))] or None
    outer_clauses = [*select, *(clause for clause in (having, node.limit, node.offset) if clause is not None)]
    _check_alias_references([*outer_clauses, *(order.expr for order in order_by or [])])

    assert node.type is not None
    node.type.tables.pop(plan.scan_alias, None)
    node.type.anonymous_tables.append(set_type)
    node.select = select
    node.select_from = ast.JoinExpr(
        table=ast.SelectSetQuery(
            initial_select_query=branch_queries[0],
            subsequent_select_queries=[
                ast.SelectSetNode(select_query=query, set_operator="UNION ALL") for query in branch_queries[1:]
            ],
            type=set_type,
        ),
        type=set_type,
    )
    node.where = None
    node.prewhere = None
    node.group_by = group_by
    node.having = having
    node.order_by = order_by


def _check_query_shape(node: ast.SelectQuery) -> None:
    assert node.select_from is not None
    if node.select_from.next_join is not None:
        # A joined row can depend on rows of another branch. The join would have to move into each branch.
        raise _Decline("joins_another_table")
    clauses = {
        "distinct": node.distinct,
        "array_join": node.array_join_op or node.array_join_list,
        "window": node.window_exprs,
        "limit_by": node.limit_by,
        "group_by_mode": node.group_by_mode,
        "with_fill": any(order.with_fill is not None for order in node.order_by or []),
    }
    for name, value in clauses.items():
        if value:
            raise _Decline(f"has_{name}")


def _branches(scan: ast.SelectQuery) -> list[_Branch]:
    assert scan.select_from is not None and isinstance(scan.select_from.table, ast.SelectSetQuery)
    branches: list[_Branch] = []
    for query in scan.select_from.table.select_queries():
        assert isinstance(query, ast.SelectQuery) and query.select_from is not None
        sample = query.select_from.sample
        if sample is not None and not sample.samples_all_rows():
            # The union applies a SAMPLE ratio in each branch. ClickHouse may pick different rows for a sample when
            # the query that reads it changes.
            raise _Decline("branch_samples")
        branches.append(
            _Branch(
                query=query,
                columns={cast(ast.Alias, column).alias: cast(ast.Alias, column).expr for column in query.select},
            )
        )
    return branches


def _clauses(node: ast.SelectQuery) -> list[ast.Expr]:
    clauses: list[ast.Expr] = [*node.select, *(node.group_by or [])]
    clauses += [clause for clause in (node.where, node.prewhere, node.having) if clause is not None]
    clauses += [order.expr for order in node.order_by or []]
    return clauses


def _aliases(node: ast.SelectQuery) -> dict[str, ast.Expr]:
    # A hidden alias on a SELECT column is still the target of a reference by that name.
    aliases = {column.alias: column.expr for column in node.select if isinstance(column, ast.Alias)}
    for name, expr in select_aliases(node, in_scope_only=True):
        aliases.setdefault(name, expr)
    return aliases


def _alias_target(node: ast.Field, plan: _Plan) -> ast.Expr | None:
    """The expression of the SELECT alias that `node` refers to, or None when it refers to no alias in the plan."""
    if isinstance(node.type, ast.FieldAliasType):
        return plan.aliases.get(node.type.alias)
    return None


def _union_column(node: ast.Field, plan: _Plan) -> str | None:
    """The branch name of the union column that `node` reads, or None when it reads something else."""
    field_type = node.type
    if isinstance(field_type, ast.PropertyType):
        # Lazy table resolution moves a property read into the union. The union exports it as its own column.
        subquery, name = field_type.joined_subquery, field_type.joined_subquery_field_name
        alias = subquery.alias if subquery is not None else None
    elif isinstance(field_type, ast.FieldType) and isinstance(field_type.table_type, ast.SelectQueryAliasType):
        alias, name = field_type.table_type.alias, field_type.name
    else:
        return None
    return plan.exported.get(name) if alias == plan.scan_alias and name is not None else None


class _Shapes:
    """Gives each expression an id. Two expressions get the same id exactly when they compute the same value from the
    same union columns. It also records which union columns each expression reads.

    A read of a union column has the id of that column. A reference to an alias has the id of the aliased
    expression. Types and source positions do not count. Each node gets its id once.
    """

    def __init__(self, plan: _Plan) -> None:
        self.plan = plan
        self._ids: dict[tuple, int] = {}
        self._reads: list[frozenset[str]] = []
        self._by_node: dict[int, int] = {}

    def shape_id(self, node: ast.AST) -> int:
        cached = self._by_node.get(id(node))
        if cached is not None:
            return cached
        shape_id = self._shape(node)
        self._by_node[id(node)] = shape_id
        return shape_id

    def reads(self, node: ast.AST) -> frozenset[str]:
        return self._reads[self.shape_id(node)]

    def _shape(self, node: ast.AST) -> int:
        if isinstance(node, ast.Alias):
            return self.shape_id(node.expr)
        if isinstance(node, ast.Field):
            column = _union_column(node, self.plan)
            if column is not None:
                return self._intern(("union", column), frozenset({column}))
            target = _alias_target(node, self.plan)
            if target is not None:
                return self.shape_id(target)
        reads: set[str] = set()
        parts = tuple(
            (item.name, self._part(getattr(node, item.name), reads))
            for item in dataclasses.fields(node)
            if item.name not in ("start", "end", "type")
        )
        return self._intern((type(node).__name__, parts), frozenset(reads))

    def _part(self, value: object, reads: set[str]) -> object:
        if isinstance(value, ast.AST):
            reads |= self.reads(value)
            return ("node", self.shape_id(value))
        if isinstance(value, list | tuple):
            return tuple(self._part(item, reads) for item in value)
        if isinstance(value, dict):
            return tuple((key, self._part(item, reads)) for key, item in sorted(value.items()))
        # The type keeps 1, 1.0 and True apart. Python equality treats them as one value.
        return (type(value).__name__, value)

    def _intern(self, shape: tuple, reads: frozenset[str]) -> int:
        shape_id = self._ids.get(shape)
        if shape_id is None:
            shape_id = self._ids[shape] = len(self._reads)
            self._reads.append(reads)
        return shape_id


class _ExpressionChecker(SyntaxVisitor):
    """Declines a clause that a branch could not evaluate the way the union does."""

    def __init__(self, plan: _Plan, shapes: _Shapes) -> None:
        super().__init__()
        self.plan = plan
        self.shapes = shapes

    def visit_field(self, node: ast.Field) -> None:
        if _union_column(node, self.plan) is not None:
            return
        field_type = node.type
        if _alias_target(node, self.plan) is not None:
            return
        if isinstance(field_type, ast.LambdaArgumentType):
            return
        raise _Decline("reads_a_field_that_is_not_a_union_column")

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        if name == "arrayjoin" or name in _ROW_POSITION_FUNCTIONS:
            raise _Decline(f"calls_{name}")
        if name == "totypename" and any(self.shapes.reads(arg) for arg in node.args):
            # The union converts each column to one type. A branch reads the type of its own table. `events.event`
            # is a String where `flag_evaluations.event` is a LowCardinality(String).
            raise _Decline("reads_the_type_of_a_union_column")
        if name == "tojsonstring" and any(self.shapes.reads(arg) for arg in node.args):
            # The union exports a JSON document as text. `toJSONString` serializes that text again. The branch's own
            # expression is the document. The printer serializes it once.
            raise _Decline("serializes_a_union_column")
        super().visit_call(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.InCohort, ast.CompareOperationOp.NotInCohort):
            # The printer turns an unresolved IN COHORT into a join after this transform runs.
            raise _Decline("in_cohort")
        super().visit_compare_operation(node)

    def _decline_subquery(self, node) -> None:
        raise _Decline("subquery_in_expression")

    visit_select_query = visit_select_set_query = _decline_subquery

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        raise _Decline("window_function")

    def visit_lambda(self, node: ast.Lambda) -> None:
        if self.plan.aliases.keys() & set(node.args):
            raise _Decline("lambda_parameter_named_like_an_alias")
        super().visit_lambda(node)


def _group_by_expression(key: ast.Expr, node: ast.SelectQuery) -> ast.Expr:
    # ClickHouse reads an integer in GROUP BY as a position in the SELECT list. The printer prints a boolean as 1 or 0.
    # A position past either end fails the query. A generated key would let it succeed.
    if isinstance(key, ast.Constant) and isinstance(key.value, int):
        if not 0 < key.value <= len(node.select):
            raise _Decline("group_by_position_out_of_range")
        column = node.select[int(key.value) - 1]
        return column.expr if isinstance(column, ast.Alias) else column
    return key


def _is_aggregate(node: ast.Call) -> bool:
    return find_hogql_aggregation(node.name) is not None


class _AggregateCollector(SyntaxVisitor):
    def __init__(self, shapes: _Shapes) -> None:
        super().__init__()
        self.shapes = shapes
        self.aggregates: dict[int, _Aggregate] = {}

    def visit_call(self, node: ast.Call) -> None:
        if not _is_aggregate(node):
            super().visit_call(node)
            return
        function = _state_function(node)
        shape_id = self.shapes.shape_id(node)
        if shape_id not in self.aggregates:
            self.aggregates[shape_id] = _Aggregate(
                call=node, function=function, column=_state_column(len(self.aggregates))
            )


def _state_function(node: ast.Call) -> str:
    """The ClickHouse aggregate whose `-State` and `-Merge` forms stand for `node`."""
    meta = find_hogql_aggregation(node.name)
    assert meta is not None
    if node.params or node.filter_expr is not None or node.order_by or node.within_group is not None:
        raise _Decline("aggregate_has_params_or_clauses")
    name = meta.clickhouse_name
    if node.distinct:
        if name != "count":
            raise _Decline(f"distinct_{name}")
        name = "countDistinct"
    if name not in _ORDER_INDEPENDENT_AGGREGATES:
        raise _Decline(f"aggregate_{name}")
    for combinator, arguments in ((f"{name}State", len(node.args)), (f"{name}Merge", 1)):
        combinator_meta = find_hogql_aggregation(combinator)
        if (
            combinator_meta is None
            or arguments < combinator_meta.min_args
            or (combinator_meta.max_args is not None and arguments > combinator_meta.max_args)
        ):
            raise _Decline(f"no_combinator_{combinator}")
    return name


class _NullLiteralFinder(SyntaxVisitor):
    """Finds a NULL literal, which ClickHouse can evaluate to Nullable(Nothing) even inside a scalar call. It follows
    select aliases, because the rewrite inlines them into each branch."""

    def __init__(self, plan: _Plan) -> None:
        super().__init__()
        self.plan = plan
        self.found = False
        self._followed: set[str] = set()

    def visit_constant(self, node: ast.Constant) -> None:
        if node.value is None:
            self.found = True

    def visit_field(self, node: ast.Field) -> None:
        if not isinstance(node.type, ast.FieldAliasType) or node.type.alias in self._followed:
            return
        self._followed.add(node.type.alias)
        target = self.plan.aliases.get(node.type.alias)
        if target is not None:
            self.visit(target)


def _check_branch_types(
    node: ast.SelectQuery, plan: _Plan, shapes: _Shapes, branches: list[_Branch], context: HogQLContext
) -> None:
    """A branch evaluates aggregate arguments and keys on its own table's columns. The union evaluates them on its
    output, which ClickHouse converts to one type. Each union column those expressions read must have the same type
    in every branch. That keeps the aggregation states of every branch the same type.

    ClickHouse returns a plain value instead of an aggregation state for an argument of type Nullable(Nothing), such
    as NULL. An argument must therefore have a known type."""
    arguments = [argument for aggregate in plan.aggregates.values() for argument in aggregate.call.args]
    for argument in arguments:
        if argument.type is None or isinstance(argument.type.resolve_constant_type(context), ast.UnknownType):
            raise _Decline("aggregate_argument_type_unknown")
        null_finder = _NullLiteralFinder(plan)
        null_finder.visit(argument)
        if null_finder.found:
            raise _Decline("aggregate_argument_has_null_literal")
    filters = [clause for clause in (node.where, node.prewhere) if clause is not None]
    columns: set[str] = set()
    for expr in [*arguments, *plan.keys, *filters]:
        columns |= shapes.reads(expr)
    for column in columns:
        types = [_column_type(branch, column, context) for branch in branches]
        if any(column_type is None or column_type != types[0] for column_type in types):
            raise _Decline(f"column_types_differ_{column}")


def _column_type(branch: _Branch, column: str, context: HogQLContext) -> ast.ConstantType | None:
    expr = branch.columns.get(column)
    if expr is None or expr.type is None:
        return None
    resolved = expr.type.resolve_constant_type(context)
    return None if isinstance(resolved, ast.UnknownType) else resolved


class _OuterRewriter(CloningVisitor):
    """Copies an outer clause with each aggregate read from its merged state and each GROUP BY key from its column."""

    def __init__(self, plan: _Plan, shapes: _Shapes, set_type: ast.SelectSetQueryType) -> None:
        super().__init__(clear_types=False)
        self.plan = plan
        self.shapes = shapes
        self.set_type = set_type
        self.key_indexes = {shapes.shape_id(key): index for index, key in enumerate(plan.keys)}

    def visit(self, node):
        if self.key_indexes and isinstance(node, ast.Expr) and not isinstance(node, ast.Constant | ast.Alias):
            index = self.key_indexes.get(self.shapes.shape_id(node))
            if index is not None:
                return self.key_field(index)
        return super().visit(node)

    def visit_field(self, node: ast.Field):
        if _union_column(node, self.plan) is not None:
            raise _Decline("reads_outside_group_by")
        return super().visit_field(node)

    def visit_call(self, node: ast.Call):
        if not _is_aggregate(node):
            return super().visit_call(node)
        aggregate = self.plan.aggregates[self.shapes.shape_id(node)]
        return ast.Call(name=aggregate.merge, args=[self._field(aggregate.column)], type=node.type)

    def key_field(self, index: int) -> ast.Field:
        return self._field(_key_column(index))

    def _field(self, name: str) -> ast.Field:
        return ast.Field(chain=[name], type=ast.FieldType(name=name, table_type=self.set_type))


class _AliasReferences(SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.defined: set[str] = set()
        self.read: set[str] = set()

    def visit_alias(self, node: ast.Alias) -> None:
        self.defined.add(node.alias)
        super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> None:
        if isinstance(node.type, ast.FieldAliasType):
            self.read.add(node.type.alias)


def _check_alias_references(clauses: list[ast.Expr]) -> None:
    """The rewrite moves WHERE, PREWHERE and aggregate arguments into the branches, with the aliases they define. A
    clause that stays in the outer query cannot read those aliases."""
    references = _AliasReferences()
    for clause in clauses:
        references.visit(clause)
    if not references.read <= references.defined:
        raise _Decline("reads_an_alias_defined_in_a_branch")


def _rewrite_select(select: list[ast.Expr], rewriter: _OuterRewriter, context: HogQLContext) -> list[ast.Expr]:
    rewritten: list[ast.Expr] = []
    names = {column.alias for column in select if isinstance(column, ast.Alias)}
    printed = printed_aliases(select)
    for column in select:
        if isinstance(column, ast.Alias):
            expr = rewriter.visit(column.expr)
            if expr != column.expr and printed[column.alias] is not column:
                # The printer drops this hidden alias. ClickHouse then names the column after its SQL.
                raise _Decline("shadowed_hidden_alias")
            rewritten.append(ast.Alias(alias=column.alias, expr=expr, hidden=column.hidden, type=column.type))
            continue
        expr = rewriter.visit(column)
        if expr == column:
            rewritten.append(expr)
            continue
        if not isinstance(column, ast.Call):
            # ClickHouse names such a column after its SQL. The rewrite changes that SQL.
            raise _Decline("unaliased_non_call_column")
        name = call_column_name(column, context)
        if name in names:
            # A later explicit alias of the same name would take this column's place. The printer drops one of them.
            raise _Decline("repeated_column_name")
        names.add(name)
        rewritten.append(ast.Alias(alias=name, expr=expr, type=column.type))
    return rewritten


class _BranchInliner(CloningVisitor):
    """Copies an expression of the outer query into a branch, with each union read as the branch's own expression."""

    def __init__(self, plan: _Plan, branch: _Branch) -> None:
        super().__init__(clear_types=False)
        self.plan = plan
        self.branch = branch
        self.alias_expansions = 0

    def visit_field(self, node: ast.Field):
        column = _union_column(node, self.plan)
        if column is not None:
            return clone_expr(self.branch.columns[column], clear_types=False)
        target = _alias_target(node, self.plan)
        if target is not None:
            self.alias_expansions += 1
            if self.alias_expansions > _MAX_ALIAS_EXPANSIONS:
                raise _Decline("alias_expansion_too_large")
            return self.visit(target)
        return super().visit_field(node)

    def visit_alias(self, node: ast.Alias):
        return self.visit(node.expr)


def _branch_query(branch: _Branch, node: ast.SelectQuery, plan: _Plan) -> ast.SelectQuery:
    inliner = _BranchInliner(plan, branch)
    outputs: list[tuple[str, ast.Expr, ast.Type | None]] = [
        (
            aggregate.column,
            ast.Call(name=aggregate.state, args=[inliner.visit(arg) for arg in aggregate.call.args]),
            aggregate.call.type,
        )
        for aggregate in plan.aggregates.values()
    ]
    key_columns = [_key_column(index) for index in range(len(plan.keys))]
    for name, key in zip(key_columns, plan.keys):
        expr = inliner.visit(key)
        outputs.append((name, expr, expr.type))
    columns: dict[str, ast.Type] = {name: column_type or ast.UnknownType() for name, _, column_type in outputs}
    where = and_conditions(
        [branch.query.where, *(inliner.visit(clause) for clause in (node.where, node.prewhere) if clause is not None)]
    )
    branch_type = cast(ast.SelectQueryType, branch.query.type)
    return ast.SelectQuery(
        select=[
            ast.Alias(alias=name, expr=expr, type=ast.FieldAliasType(alias=name, type=columns[name]))
            for name, expr, _ in outputs
        ],
        select_from=branch.query.select_from,
        where=where,
        prewhere=branch.query.prewhere,
        group_by=[
            ast.Field(chain=[name], type=ast.FieldAliasType(alias=name, type=columns[name])) for name in key_columns
        ]
        or None,
        settings=branch.query.settings,
        type=dataclasses.replace(branch_type, columns=columns),
    )
