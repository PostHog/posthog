"""Walk a prepared HogQL tree and attribute conditions to the events reads they constrain.

The tree comes out of ``prepare_ast_for_printing``, so lazy tables are expanded, saved views are
inlined and every node carries a type. The checks match on those types instead of chain strings,
because ``sharded_events`` only exists at print time and a column can reach the events table
through any number of view, subquery and alias layers.

A condition belongs to the events read whose ``TableType`` node its field resolves to, compared by
identity. ``TableType`` compares equal by value, so identity is the only thing that separates two
reads of the same table.
"""

from collections.abc import Iterator

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

# More hops than this to reach a real table means a resolver bug or a cycle, so give up rather
# than loop.
_MAX_COLUMN_HOPS = 32

# Join types whose ``ON`` condition constrains both sides, so a term in it prunes the read the same
# way a ``where`` term does. An outer join keeps the rows that fail the condition and an anti join
# keeps only those, so neither prunes. A cross-shard join carries a ``GLOBAL`` prefix and prunes
# the same way.
_INNER_JOIN_TYPES = frozenset(
    {
        "JOIN",
        "INNER",
        "INNER JOIN",
        "ANY INNER JOIN",
        "ALL INNER JOIN",
        "ASOF INNER JOIN",
        "SEMI JOIN",
        "ASOF SEMI JOIN",
    }
)


@frozen(eq=False)
class EventsRead:
    select: ast.SelectQuery
    table_type: ast.TableType


def find_events_reads(node: ast.AST) -> list[EventsRead]:
    collector = _EventsReadCollector()
    collector.visit(node)
    return collector.reads


def collect_conditions(node: ast.AST, read: EventsRead) -> list[ast.Expr]:
    """Top-level AND terms of every ``where``, ``prewhere`` and inner-join ``ON`` that constrains
    ``read``.

    A term from an enclosing query counts, because ClickHouse pushes a condition on a subquery's
    or a view's column down into the read. It stops counting at a subquery that slices its own
    rows, which hands up its choice of rows before the outer condition sees them.
    """
    collector = _ConditionCollector()
    collector.visit(node)
    reaching = collector.selects_reaching(read.select)
    return [term for select, term in collector.terms if id(select) in reaching]


def iter_and_terms(expr: ast.Expr | None) -> Iterator[ast.Expr]:
    if expr is None:
        return
    unwrapped = strip_aliases(expr)
    if isinstance(unwrapped, ast.And):
        for child in unwrapped.exprs:
            yield from iter_and_terms(child)
        return
    yield unwrapped


def strip_aliases(expr: ast.Expr) -> ast.Expr:
    # The resolver passes re-wrap, so aliases can stack.
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def is_column_of(expr: ast.Expr, read: EventsRead, column: str) -> bool:
    """Whether ``expr`` is a bare reference to ``column`` on ``read``, through any number of
    view, subquery and alias layers."""
    expr = strip_aliases(expr)
    if not isinstance(expr, ast.Field):
        return False
    return any(
        name == column and table_type is read.table_type for table_type, name in resolve_to_table_columns(expr.type)
    )


def contains_column_of(expr: ast.Expr, read: EventsRead, column: str) -> bool:
    finder = _ColumnFinder(read=read, column=column)
    finder.visit(expr)
    return finder.found


def resolve_to_table_columns(type_: ast.Type | None) -> list[tuple[ast.TableType, str]]:
    """Follow a field's type down to the database table columns it exports.

    A view or subquery column is a ``FieldType`` whose own type is the expression that select
    exported, which may again be a column of a deeper select. A set query exports one column per
    branch, and a condition on it constrains every branch, so the walk forks and can reach more
    than one table.
    """
    resolved: list[tuple[ast.TableType, str]] = []
    pending: list[tuple[ast.Type | None, int]] = [(type_, 0)]
    seen: set[int] = set()

    while pending:
        current, hops = pending.pop()
        if hops >= _MAX_COLUMN_HOPS or id(current) in seen:
            continue
        seen.add(id(current))
        while isinstance(current, ast.FieldAliasType):
            current = current.type
        if not isinstance(current, ast.FieldType):
            continue
        table_type = _unwrap_table_alias(current.table_type)
        if isinstance(table_type, ast.TableType):
            resolved.append((table_type, _physical_column_name(current)))
            continue
        select_type = _select_type_of(table_type)
        if select_type is None:
            continue
        pending.extend((column, hops + 1) for column in _exported_columns(select_type, current.name))

    return resolved


def _physical_column_name(field_type: ast.FieldType) -> str:
    """The database column a field names.

    ``FROM events AS e (id, kind, props, ts)`` renames the table's columns for the query and the
    field keeps the query's name, so map it back the way ``FieldType.resolve_database_field`` does.
    """
    table_type = field_type.table_type
    if isinstance(table_type, ast.ColumnAliasedTableType):
        return table_type.alias_to_original.get(field_type.name, field_type.name)
    return field_type.name


def _unwrap_table_alias(table_type: ast.Type) -> ast.Type:
    while isinstance(table_type, ast.TableAliasType | ast.ColumnAliasedTableType):
        table_type = table_type.table_type
    if isinstance(table_type, ast.CTETableAliasType):
        return table_type.cte_table_type
    return table_type


def _select_type_of(table_type: ast.Type) -> ast.SelectQueryType | ast.SelectSetQueryType | None:
    if isinstance(table_type, ast.SelectQueryType | ast.SelectSetQueryType):
        return table_type
    if isinstance(table_type, ast.SelectQueryAliasType | ast.SelectViewType | ast.CTETableType):
        return table_type.select_query_type
    return None


def _exported_columns(select_type: ast.SelectQueryType | ast.SelectSetQueryType, name: str) -> list[ast.Type]:
    """Each type a select exports under ``name``: one for a plain select, one per branch for a
    set query, whose own entry is a type unified across the branches and holds no lineage."""
    if isinstance(select_type, ast.SelectSetQueryType):
        return [column for branch in select_type.types for column in _exported_columns(branch, name)]
    column = select_type.columns.get(name)
    return [column] if column is not None else []


def _slices_rows(select: ast.SelectQuery) -> bool:
    """Whether this select picks which of its rows to keep, so a condition applied above it
    cannot reach the read below.

    ``LIMIT``, ``OFFSET`` and ``LIMIT BY`` all do, because the rows come in the select's own order
    and filtering earlier would keep different ones. The outermost select always carries the query
    limit, which costs nothing here because no condition sits above it.
    """
    return select.limit is not None or select.offset is not None or select.limit_by is not None


def _inner_join_terms(join: ast.JoinExpr | None) -> Iterator[ast.Expr]:
    """Top-level AND terms of every inner-join ``ON`` condition in this select's join chain.

    A ``USING`` list only pairs columns of the two tables, so it is left out.
    """
    while join is not None:
        join_type = join.join_type or ""
        constraint = join.constraint
        if (
            join_type.removeprefix("GLOBAL ") in _INNER_JOIN_TYPES
            and constraint is not None
            and constraint.constraint_type == "ON"
        ):
            yield from iter_and_terms(constraint.expr)
        join = join.next_join


def _events_table_type(join: ast.JoinExpr) -> ast.TableType | None:
    join_type = join.type
    if join_type is None:
        return None
    table_type = _unwrap_table_alias(join_type)
    if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
        return table_type
    return None


class _EventsReadCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[EventsRead] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        join = node.select_from
        while join is not None:
            table_type = _events_table_type(join)
            if table_type is not None:
                self.reads.append(EventsRead(select=node, table_type=table_type))
            join = join.next_join
        super().visit_select_query(node)


class _ConditionCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.terms: list[tuple[ast.SelectQuery, ast.Expr]] = []
        self._enclosing_select: dict[int, ast.SelectQuery] = {}
        self._stack: list[ast.SelectQuery] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if self._stack:
            self._enclosing_select[id(node)] = self._stack[-1]
        self.terms.extend((node, term) for term in iter_and_terms(node.where))
        self.terms.extend((node, term) for term in iter_and_terms(node.prewhere))
        self.terms.extend((node, term) for term in _inner_join_terms(node.select_from))
        self._stack.append(node)
        super().visit_select_query(node)
        self._stack.pop()

    def selects_reaching(self, select: ast.SelectQuery) -> set[int]:
        """The ids of the selects whose conditions constrain a read in ``select``: the select
        itself, then each enclosing one until a row slice blocks the way."""
        reaching = {id(select)}
        current = select
        while not _slices_rows(current):
            enclosing = self._enclosing_select.get(id(current))
            if enclosing is None:
                break
            reaching.add(id(enclosing))
            current = enclosing
        return reaching


class _ColumnFinder(TraversingVisitor):
    def __init__(self, *, read: EventsRead, column: str) -> None:
        super().__init__()
        self.read = read
        self.column = column
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if is_column_of(node, self.read, self.column):
            self.found = True
        super().visit_field(node)
