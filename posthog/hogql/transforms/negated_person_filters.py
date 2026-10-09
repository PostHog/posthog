"""Replace negated person-property filters with an exclusion of the persons that fail them.

On `events`, a filter such as `person.properties.email NOT ILIKE '%@internal.com%'` makes the query LEFT JOIN a subquery
that reads every person in the team. This transform replaces those filters with

    <person key> NOT IN (SELECT id FROM persons WHERE NOT (<the filters, on persons.properties>))

The persons lazy table turns that subquery into an argMax over only the persons that have a row which fails a filter
(see `select_from_persons_table`), so the cost follows the number of excluded persons, not the size of the team.

Both forms give each row the same verdict. Both judge a person in the persons table by its latest version. A row whose
person is not in the persons table (no person, a deleted person, a person created in the future) gets NULL properties
from the join. Every filter shape that this transform accepts is true for NULL, so the join keeps that row, and the
exclusion does not contain its person.

The forms differ when a person has two unmerged rows at its latest version. The join returns both rows, so it counts
the event once for each row that passes the filters. The exclusion judges the person by one of the two rows and counts
the event once or not at all.
"""

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeGuard, TypeVar, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import PERSONS
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.persons import persons_join_is_inner
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.dataclasses import frozen
from posthog.schema_enums import MaterializationMode

if TYPE_CHECKING:
    from posthog.clickhouse.materialized_column_types import MaterializedColumn
    from posthog.property_columns import PropertyName, TableColumn

_T_AST = TypeVar("_T_AST", bound=ast.AST)
_MaterializedColumns = Mapping[tuple["PropertyName", "TableColumn"], "MaterializedColumn"]

# With a non-NULL constant on one side, the printer makes each of these true when the property is NULL.
_NEGATED_COMPARISONS = frozenset(
    {
        ast.CompareOperationOp.NotEq,
        ast.CompareOperationOp.NotLike,
        ast.CompareOperationOp.NotILike,
        ast.CompareOperationOp.NotRegex,
        ast.CompareOperationOp.NotIRegex,
        ast.CompareOperationOp.NotIn,
    }
)


def rewrite_negated_person_filters(node: _T_AST, context: HogQLContext) -> _T_AST | None:
    """Returns None when no SELECT qualifies. Otherwise it emits untyped nodes. The caller runs type resolution again."""
    # This mode reads the properties JSON instead of materialized columns. See `_all_materialized` for why that costs
    # more than the join.
    if context.modifiers.materializationMode == MaterializationMode.DISABLED:
        return None
    planner = _Planner()
    planner.visit(node)
    # The exclusion reads `FROM persons`. A CTE with that name would replace the persons table in it.
    if planner.defines_persons_cte:
        return None
    if not planner.rewrites:
        return None
    columns = _materialized_person_columns()
    rewrites = {
        key: rewrite for key, rewrite in planner.rewrites.items() if _all_materialized(rewrite.properties, columns)
    }
    # An INNER JOIN drops the rows that have no persons row. The exclusion would keep them.
    if not rewrites or persons_join_is_inner(context):
        return None
    return cast(_T_AST, _Rewriter(rewrites).visit(node))


@frozen
class _Rewrite:
    kept: list[ast.Expr]
    exclusion: ast.Expr
    properties: list[list[str | int]]


def _plan(node: ast.SelectQuery) -> _Rewrite | None:
    select_from = node.select_from
    if (
        node.where is None
        or not isinstance(node.type, ast.SelectQueryType)
        or select_from is None
        or not _is_events(select_from.type)
    ):
        return None

    join: ast.LazyJoinType | None = None
    path: list[str] | None = None
    excluded: list[ast.Expr] = []
    kept: list[ast.Expr] = []
    for conjunct in top_level_conjuncts(node.where):
        conjunct_join = _join_when_true_for_null(conjunct)
        if conjunct_join is not None:
            root, conjunct_path = _root_and_path(conjunct_join)
            if root is select_from.type and path in (None, conjunct_path):
                join, path = conjunct_join, conjunct_path
                excluded.append(conjunct)
                continue
        kept.append(conjunct)
    if join is None or path is None:
        return None

    reader = _PersonsJoinReader(select_from.type, skip=excluded)
    reader.visit(node)
    if reader.found:
        return None

    # The resolver looks up a SELECT alias before a bare field, so the key names its table.
    person_key = [get_long_table_name(node.type, select_from.type), *path[:-1], *join.lazy_join.from_field]
    rebinder = _PersonsPropertyRebinder()
    filters = [rebinder.visit(conjunct) for conjunct in excluded]
    return _Rewrite(kept=kept, exclusion=_exclusion(person_key, filters), properties=rebinder.properties)


def _materialized_person_columns() -> _MaterializedColumns:
    # Deferred: the registry is a Django-side lookup, and the printer package must import without Django.
    from posthog.clickhouse.materialized_columns import get_enabled_materialized_columns_by_table  # noqa: PLC0415

    return get_enabled_materialized_columns_by_table().get("person", {})


def _all_materialized(properties: list[list[str | int]], columns: _MaterializedColumns) -> bool:
    """True when each person property has a materialized column.

    The persons subquery finds its candidates in every row of every person, across all versions. For a property without a
    materialized column, it reads the whole properties JSON of each row. That costs more than the join, which reads
    properties only for the latest row of each person.
    """
    return all(len(chain) == 1 and (str(chain[0]), "properties") in columns for chain in properties)


def _is_events(table_type: ast.Type | None) -> TypeGuard[ast.TableType | ast.TableAliasType]:
    if isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)


def _exclusion(person_key: list[str | int], filters: list[ast.Expr]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Field(chain=person_key),
        right=ast.SelectQuery(
            select=[ast.Field(chain=["id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=ast.Not(expr=_and(filters)),
        ),
    )


def _and(exprs: list[ast.Expr]) -> ast.Expr:
    return exprs[0] if len(exprs) == 1 else ast.And(exprs=exprs)


def _join_when_true_for_null(expr: ast.Expr) -> ast.LazyJoinType | None:
    """The persons join that `expr` filters, when `expr` has a shape that property_to_expr builds for a negated operator."""
    match expr:
        case ast.CompareOperation(op=op, left=left, right=right) if op in _NEGATED_COMPARISONS and _is_literal(right):
            return _persons_join(left)
        case ast.Not(expr=negated):
            return _join_when_false_for_null(negated)
        # not_regex builds ifNull(not(match(toString(property), pattern)), 1).
        case ast.Call(
            name="ifNull",
            args=[ast.Call(name="not", args=[ast.Call(name="match", args=[searched, pattern])]), fallback],
        ) if _is_int(fallback, 1) and _is_literal(pattern):
            return _persons_join(searched)
    return None


def _join_when_false_for_null(expr: ast.Expr) -> ast.LazyJoinType | None:
    match expr:
        # A multi-value not_icontains negates multiSearchAnyCaseInsensitive(...) > 0. It has one OR term per chunk of
        # needles.
        case ast.Or(exprs=terms):
            joins = [_join_when_false_for_null(term) for term in terms]
            first = joins[0]
            if first is None or any(join is None or not _same_join(first, join) for join in joins):
                return None
            return first
        case ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Call(name="multiSearchAnyCaseInsensitive", args=[searched, needles]),
            right=zero,
        ) if _is_int(zero, 0) and _is_literal(needles):
            return _persons_join(searched)
    return None


def _persons_join(expr: ast.Expr) -> ast.LazyJoinType | None:
    """The persons join that `expr` reads, when `expr` is `person.properties.<key>`, alone or inside toString()."""
    if isinstance(expr, ast.Call) and expr.name == "toString" and len(expr.args) == 1:
        expr = expr.args[0]
    if isinstance(expr, ast.Alias) and expr.hidden:
        expr = expr.expr
    if not isinstance(expr, ast.Field) or not isinstance(expr.type, ast.PropertyType):
        return None
    field_type = expr.type.field_type
    join = field_type.table_type
    if field_type.name != "properties" or not isinstance(join, ast.LazyJoinType) or join.lazy_join.resolver != PERSONS:
        return None
    return join


def _is_literal(expr: ast.Expr) -> bool:
    # WhereClauseExtractor.visit_not reads any bool constant as its marker for a filter that it cannot lift. It then
    # gives up on the candidate prefilter, and the persons subquery reads every person.
    if isinstance(expr, ast.Constant):
        return expr.value is not None and not isinstance(expr.value, bool)
    if isinstance(expr, ast.Tuple | ast.Array):
        return bool(expr.exprs) and all(_is_literal(item) for item in expr.exprs)
    return False


def _is_int(expr: ast.Expr, value: int) -> bool:
    return isinstance(expr, ast.Constant) and type(expr.value) is int and expr.value == value


def _root_and_path(join: ast.LazyJoinType) -> tuple[ast.Type, list[str]]:
    """The table that `join` hangs off, and the lazy-join fields from it to `join`, such as ["pdi", "person"]."""
    path: list[str] = []
    table_type: ast.Type = join
    while isinstance(table_type, ast.LazyJoinType):
        path.insert(0, table_type.field)
        table_type = table_type.table_type
    return table_type, path


def _same_join(left: ast.LazyJoinType, right: ast.LazyJoinType) -> bool:
    left_root, left_path = _root_and_path(left)
    right_root, right_path = _root_and_path(right)
    return left_root is right_root and left_path == right_path


def _reads_persons_join(field_type: ast.Type | None, root: ast.Type) -> bool:
    current = field_type
    while current is not None:
        if isinstance(current, ast.LazyJoinType):
            if current.lazy_join.resolver == PERSONS and _root_and_path(current)[0] is root:
                return True
            current = current.table_type
        elif isinstance(current, ast.PropertyType):
            current = current.field_type
        elif isinstance(current, ast.FieldAliasType):
            current = current.type
        elif isinstance(current, ast.FieldType | ast.AsteriskType | ast.VirtualTableType):
            current = current.table_type
        else:
            return False
    return False


class _PersonsJoinReader(TraversingVisitor):
    """Finds a field of one SELECT, outside the filters in `skip`, that reads a persons join off `root`."""

    def __init__(self, root: ast.Type, skip: list[ast.Expr]) -> None:
        super().__init__()
        self.root = root
        self.skip = {id(expr) for expr in skip}
        self.found = False
        self.entered = False

    def visit(self, node: ast.AST | None) -> None:
        if not self.found and node is not None and id(node) not in self.skip:
            super().visit(node)

    # A nested SELECT resolves its fields in its own scope, so its fields cannot read this SELECT's joins.
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if not self.entered:
            self.entered = True
            super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_field(self, node: ast.Field) -> None:
        if _reads_persons_join(node.type, self.root):
            self.found = True


class _PersonsPropertyRebinder(CloningVisitor):
    """Clones a filter on `person.properties.<key>` into the same filter on `properties.<key>` of `persons`."""

    def __init__(self) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.properties: list[list[str | int]] = []

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        if node.hidden:
            return self.visit(node.expr)
        return super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if isinstance(node.type, ast.PropertyType):
            self.properties.append(node.type.chain)
            return ast.Field(chain=["properties", *node.type.chain])
        return super().visit_field(node)


class _Planner(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.rewrites: dict[int, _Rewrite] = {}
        self.defines_persons_cte = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.ctes and "persons" in node.ctes:
            self.defines_persons_cte = True
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
        rewrite = self.rewrites.get(id(node))
        if rewrite is None:
            return super().visit_select_query(node)
        query = super().visit_select_query(dataclasses.replace(node, where=None))
        query.where = _and([*(self.visit(conjunct) for conjunct in rewrite.kept), rewrite.exclusion])
        return query
