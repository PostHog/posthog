from dataclasses import replace
from typing import Optional, cast

import structlog

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoin, LazyJoinToAdd, LazyTable, Table
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor, clone_expr

logger = structlog.get_logger(__name__)


def build_distinct_id_pushdown(person_id_filter: ast.Expr) -> ast.CompareOperation:
    inner = cast(
        ast.SelectQuery,
        parse_select("SELECT distinct_id FROM raw_person_distinct_ids AS pdi_pushdown_pdi"),
    )
    inner.where = clone_expr(person_id_filter, clear_types=True, clear_locations=True)
    return ast.CompareOperation(
        left=ast.Field(chain=["distinct_id"]),
        right=inner,
        op=ast.CompareOperationOp.In,
    )


def derive_person_id_filter(
    node: ast.SelectQuery,
    join_to_add: LazyJoinToAdd,
    *,
    context: HogQLContext,
    from_field_maps_to_person_id: bool,
) -> Optional[ast.Expr]:
    try:
        return _derive_person_id_filter_inner(
            node, join_to_add, context=context, from_field_maps_to_person_id=from_field_maps_to_person_id
        )
    except Exception as e:
        logger.warning("pdi_person_id_pushdown_failed", error=str(e))
        return None


def _derive_person_id_filter_inner(
    node: ast.SelectQuery,
    join_to_add: LazyJoinToAdd,
    *,
    context: HogQLContext,
    from_field_maps_to_person_id: bool,
) -> Optional[ast.Expr]:
    if not node.where and not node.prewhere:
        return None

    if from_field_maps_to_person_id:
        persons_table = _find_persons_table(node)
        if persons_table is not None:
            extractor = WhereClauseExtractor(context)
            extractor.tracked_tables.append(persons_table)
            persons_filter = extractor.get_inner_where(_strip_next_join(node))
            if persons_filter is not None:
                inner_persons = cast(
                    ast.SelectQuery,
                    parse_select("SELECT id FROM raw_persons AS pdi_pushdown_persons"),
                )
                inner_persons.where = persons_filter
                return ast.CompareOperation(
                    left=ast.Field(chain=["person_id"]),
                    right=inner_persons,
                    op=ast.CompareOperationOp.In,
                )

    pdi_table = join_to_add.lazy_join.join_table
    if not isinstance(pdi_table, (Table, LazyTable, LazyJoin)):
        return None

    matches: list[ast.CompareOperation] = []
    for source in (node.where, node.prewhere):
        if source is not None:
            _collect_pdi_person_id_in_filters(source, pdi_table=pdi_table, out=matches)
    if not matches:
        return None

    person_id_filters = [_rewrite_to_person_id(expr) for expr in matches]
    if len(person_id_filters) == 1:
        return person_id_filters[0]
    return ast.And(exprs=person_id_filters)


class _FindPersonsTableVisitor(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found: Optional[object] = None

    def visit(self, node):
        if self.found is not None:
            return
        super().visit(node)

    def visit_field(self, node: ast.Field) -> None:
        from posthog.hogql.database.schema.persons import PersonsTable

        table_type = _table_type_from_field(node)
        if isinstance(table_type, ast.LazyTableType) and isinstance(table_type.table, PersonsTable):
            self.found = table_type.table


def _strip_next_join(node: ast.SelectQuery) -> ast.SelectQuery:
    if node.select_from is None or node.select_from.next_join is None:
        return node
    return replace(node, select_from=replace(node.select_from, next_join=None))


def _find_persons_table(node: ast.SelectQuery):
    visitor = _FindPersonsTableVisitor()
    if node.where is not None:
        visitor.visit(node.where)
    if visitor.found is None and node.prewhere is not None:
        visitor.visit(node.prewhere)
    return visitor.found


def _table_type_from_field(node: ast.Field):
    t = node.type
    if isinstance(t, ast.PropertyType):
        t = t.field_type
    if isinstance(t, ast.FieldAliasType):
        inner = t.type
        while isinstance(inner, ast.FieldAliasType):
            inner = inner.type
        if isinstance(inner, ast.PropertyType):
            inner = inner.field_type
        t = inner
    if isinstance(t, ast.FieldType):
        tt = t.table_type
        while isinstance(tt, ast.TableAliasType):
            tt = tt.table_type
        return tt
    return None


def _collect_pdi_person_id_in_filters(
    expr: ast.Expr,
    *,
    pdi_table,
    out: list[ast.CompareOperation],
) -> None:
    # Intentionally does NOT descend into Or/Not: a person_id IN (X) inside
    # an OR cannot be safely promoted as a hard filter.
    if isinstance(expr, ast.CompareOperation):
        if expr.op == ast.CompareOperationOp.In and _is_pdi_person_id_field(expr.left, pdi_table=pdi_table):
            out.append(expr)
        return
    if isinstance(expr, ast.And):
        for sub in expr.exprs:
            _collect_pdi_person_id_in_filters(sub, pdi_table=pdi_table, out=out)
        return
    if isinstance(expr, ast.Call) and expr.name == "and":
        for sub in expr.args:
            _collect_pdi_person_id_in_filters(sub, pdi_table=pdi_table, out=out)


def _is_pdi_person_id_field(expr: ast.Expr, *, pdi_table) -> bool:
    field_type = _unwrap_to_field_type(expr)
    if field_type is None or field_type.name != "person_id":
        return False
    return _table_is(field_type.table_type, pdi_table)


def _unwrap_to_field_type(expr: ast.Expr):
    e = expr
    while isinstance(e, ast.Alias):
        if e.type is not None and isinstance(e.type, ast.FieldAliasType):
            inner_type = e.type.type
            while isinstance(inner_type, ast.FieldAliasType):
                inner_type = inner_type.type
            if isinstance(inner_type, ast.FieldType):
                return inner_type
        e = e.expr

    if isinstance(e, ast.Field):
        if isinstance(e.type, ast.FieldType):
            return e.type
        if isinstance(e.type, ast.FieldAliasType):
            inner = e.type.type
            while isinstance(inner, ast.FieldAliasType):
                inner = inner.type
            if isinstance(inner, ast.FieldType):
                return inner
    return None


def _table_is(table_type, target) -> bool:
    if isinstance(table_type, ast.LazyTableType):
        return table_type.table is target
    if isinstance(table_type, ast.LazyJoinType):
        return table_type.lazy_join.join_table is target
    if isinstance(table_type, ast.TableAliasType):
        return _table_is(table_type.table_type, target)
    return False


def _rewrite_to_person_id(expr: ast.CompareOperation) -> ast.Expr:
    return ast.CompareOperation(
        left=ast.Field(chain=["person_id"]),
        right=clone_expr(expr.right, clear_types=True, clear_locations=True),
        op=expr.op,
    )
