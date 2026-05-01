from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoin, LazyJoinToAdd, LazyTable, Table
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clone_expr


# Filter on a distinct_id IN subquery on raw_person_distinct_ids is the only safe
# way to narrow person_distinct_id2 by person_id. The naive WHERE person_id IN (X)
# would filter raw rows pre-argMax and report stale mappings for distinct_ids that
# were rebound to a different person.
def build_distinct_id_pushdown(person_id_filter: ast.Expr) -> ast.CompareOperation:
    inner = cast(
        ast.SelectQuery,
        parse_select("SELECT distinct_id FROM raw_person_distinct_ids"),
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
    if not node.where:
        return None

    # Primary: reuse WhereClauseExtractor to extract any persons-side predicate
    # (id IN, email =, properties.* IN, ...). Translate into a person_id filter
    # by wrapping with a SELECT against raw_persons. This mirrors the inner
    # subquery shape that select_from_persons_table already emits, just consumed
    # by pdi instead.
    if from_field_maps_to_person_id:
        # By the time persons_pdi_join runs, the persons FROM has already been
        # rewritten to a SelectQueryAliasType (see lazy_tables.py). However, field
        # references in node.where still carry the original PersonsTable instance,
        # so we recover it from there to feed WhereClauseExtractor.
        persons_table = _find_persons_table_in_where(node.where)
        if persons_table is not None:
            extractor = WhereClauseExtractor(context)
            if persons_table not in extractor.tracked_tables:
                extractor.tracked_tables.append(persons_table)
            persons_filter = extractor.get_inner_where(node)
            if persons_filter is not None:
                inner_persons = cast(
                    ast.SelectQuery,
                    parse_select("SELECT id FROM raw_persons"),
                )
                inner_persons.where = persons_filter
                return ast.CompareOperation(
                    left=ast.Field(chain=["person_id"]),
                    right=inner_persons,
                    op=ast.CompareOperationOp.In,
                )

    # Fallback: direct pdi.person_id IN (X) anywhere in the outer WHERE.
    pdi_table = join_to_add.lazy_join.join_table
    if not isinstance(pdi_table, (Table, LazyTable, LazyJoin)):
        return None

    matches: list[ast.CompareOperation] = []
    _collect_pdi_person_id_in_filters(node.where, pdi_table=pdi_table, out=matches)
    if not matches:
        return None

    person_id_filters = [_rewrite_to_person_id(expr) for expr in matches]
    if len(person_id_filters) == 1:
        return person_id_filters[0]
    return ast.And(exprs=person_id_filters)


def _find_persons_table_in_where(where: Optional[ast.Expr]):
    """Walk a WHERE expression and return the first PersonsTable instance referenced."""
    from posthog.hogql.database.schema.persons import PersonsTable

    if where is None:
        return None

    found: list = []

    def _table_from_field(expr) -> Optional[ast.Type]:
        t = expr.type
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

    def _walk(expr):
        if isinstance(expr, ast.Field):
            tt = _table_from_field(expr)
            if isinstance(tt, ast.LazyTableType) and isinstance(tt.table, PersonsTable):
                found.append(tt.table)
                return
        if isinstance(expr, ast.Alias):
            _walk(expr.expr)
            return
        if isinstance(expr, ast.CompareOperation):
            _walk(expr.left)
            if not found:
                _walk(expr.right)
            return
        if isinstance(expr, ast.And) or isinstance(expr, ast.Or):
            for sub in expr.exprs:
                _walk(sub)
                if found:
                    return
            return
        if isinstance(expr, ast.Not):
            _walk(expr.expr)
            return
        if isinstance(expr, ast.Call):
            for arg in expr.args:
                _walk(arg)
                if found:
                    return
            return
        if isinstance(expr, ast.Tuple):
            for sub in expr.exprs:
                _walk(sub)
                if found:
                    return

    _walk(where)
    return found[0] if found else None


def _collect_pdi_person_id_in_filters(
    expr: ast.Expr,
    *,
    pdi_table,
    out: list[ast.CompareOperation],
) -> None:
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
