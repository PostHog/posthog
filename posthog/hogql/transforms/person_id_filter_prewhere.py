"""Add a PREWHERE that narrows an events_json read to the rows that a `person_id` filter can keep.

With person-id overrides, `events.person_id` reads the overrides join:

    if(not(empty(override.distinct_id)), override.person_id, event_person_id)

ClickHouse evaluates `person_id = <id>` after that join. It reads every selected column of every row in the time
range, and then drops almost all of the rows. For `person_id = <id>` and `person_id IN (<ids>)`, this transform adds

    PREWHERE event_person_id = <id>
          OR distinct_id IN (SELECT distinct_id FROM raw_person_distinct_id_overrides WHERE person_id = <id>)

The PREWHERE keeps a superset of the rows that the filter keeps, and the filter stays in the WHERE. A row passes the
filter through its override or through its stored person id. A row with an override to the person has its
distinct_id in the subquery. A row without an override has the person as its stored person id.

The subquery is a local IN. Each shard then reads the candidates and resolves the person from the same snapshot of
the overrides table. A GLOBAL IN reads the candidates on the initiator, and it can miss an override that a shard
already has.

The transform applies to events_json only. That table has bloom filter indexes on `distinct_id` and `person_id`.
"""

from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.dataclasses import frozen

_OVERRIDES_TABLE = "raw_person_distinct_id_overrides"
_PUSHED_COMPARISONS = frozenset({ast.CompareOperationOp.Eq, ast.CompareOperationOp.In})


def add_person_id_filter_prewhere(node: _T_AST, context: HogQLContext) -> _T_AST | None:
    """Returns None when no SELECT qualifies. Otherwise it emits untyped nodes. The caller runs type resolution again."""
    planner = _Planner()
    planner.visit(node)
    if planner.blocks_rewrite or not planner.rewrites or not context.uses_new_events_schema():
        return None
    return cast(_T_AST, _Rewriter(planner.rewrites).visit(node))


@frozen
class _Rewrite:
    prewhere: ast.Expr


def _plan(node: ast.SelectQuery) -> _Rewrite | None:
    select_from = node.select_from
    if (
        node.where is None
        # An explicit PREWHERE stops ClickHouse from moving WHERE conditions there. The author of the query chose what
        # runs first.
        or node.prewhere is not None
        or not isinstance(node.type, ast.SelectQueryType)
        or select_from is None
        or not _is_events(select_from.type)
    ):
        return None
    events = select_from.type
    for conjunct in top_level_conjuncts(node.where):
        if (
            isinstance(conjunct, ast.CompareOperation)
            and conjunct.op in _PUSHED_COMPARISONS
            and _is_overridden_person_id(conjunct.left, events)
            and _is_literal(conjunct.right)
        ):
            # The resolver looks up a SELECT alias before a bare field, so the fields name their table.
            table = get_long_table_name(node.type, events)
            return _Rewrite(prewhere=_prewhere(table, conjunct.op, conjunct.right))
    return None


def _is_events(table_type: ast.Type | None) -> bool:
    if isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)


def _unwrap(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias) and expr.hidden:
        expr = expr.expr
    return expr


def _is_overridden_person_id(expr: ast.Expr, events: ast.Type | None) -> bool:
    """True for `person_id` of `events`, as the resolver expands it when the person comes from the overrides join.

    In every other persons-on-events mode `person_id` is a plain field or reads another join, and this is False.
    """
    if not isinstance(expr, ast.Alias) or not expr.hidden or expr.alias != "person_id":
        return False
    call = _unwrap(expr)
    if not isinstance(call, ast.Call) or call.name != "if" or len(call.args) != 3:
        return False
    stored = _unwrap(call.args[2])
    return (
        isinstance(stored, ast.Field)
        and isinstance(stored.type, ast.FieldType)
        and stored.type.name == "event_person_id"
        and stored.type.table_type is events
    )


def _is_literal(expr: ast.Expr) -> bool:
    if isinstance(expr, ast.Constant):
        return _is_literal_value(expr.value)
    if isinstance(expr, ast.Tuple | ast.Array):
        return bool(expr.exprs) and all(_is_literal(item) for item in expr.exprs)
    return False


def _is_literal_value(value: object) -> bool:
    if isinstance(value, list | tuple):
        return bool(value) and all(_is_literal_value(item) for item in value)
    return value is not None and not isinstance(value, bool)


def _prewhere(table: str, op: ast.CompareOperationOp, person_ids: ast.Expr) -> ast.Expr:
    cloner = CloningVisitor(clear_types=True, clear_locations=True)
    return ast.Or(
        exprs=[
            ast.CompareOperation(
                op=op, left=ast.Field(chain=[table, "event_person_id"]), right=cloner.visit(person_ids)
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=[table, "distinct_id"]),
                right=ast.SelectQuery(
                    select=[ast.Field(chain=["distinct_id"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[_OVERRIDES_TABLE])),
                    where=ast.CompareOperation(
                        op=op, left=ast.Field(chain=["person_id"]), right=cloner.visit(person_ids)
                    ),
                ),
            ),
        ]
    )


class _Planner(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.rewrites: dict[int, _Rewrite] = {}
        self.blocks_rewrite = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # The PREWHERE reads the overrides table by name. A CTE with that name would replace the table in it.
        if node.ctes and _OVERRIDES_TABLE in node.ctes:
            self.blocks_rewrite = True
        # The caller resolves the whole tree again. That drops the isolated scope of expanded expression fields such as
        # `events.person_id`, so their unqualified inner fields become ambiguous in a SELECT that joins two tables.
        if node.select_from is not None and node.select_from.next_join is not None:
            self.blocks_rewrite = True
        rewrite = _plan(node)
        if rewrite is not None:
            self.rewrites[id(node)] = rewrite
        super().visit_select_query(node)

    def visit_field(self, node: ast.Field) -> None:
        pass


class _Rewriter(CloningVisitor):
    def __init__(self, rewrites: dict[int, _Rewrite]) -> None:
        super().__init__(clear_types=True)
        self.rewrites = rewrites

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        query = super().visit_select_query(node)
        rewrite = self.rewrites.get(id(node))
        if rewrite is not None:
            query.prewhere = rewrite.prewhere
        return query
