"""Walk a prepared HogQL tree and attribute conditions to the events reads they constrain.

The tree the checks see comes out of ``prepare_ast_for_printing``, so every node carries a
type, lazy tables are expanded and saved views are inlined. That lets the checks work from
types instead of chain strings: ``sharded_events`` only exists at print time, and a column
can reach the events table through any number of view, subquery and alias layers.

A condition is attributed to an events read by the identity of the ``TableType`` node that
both the read's ``JoinExpr`` and the condition's field resolve to. Identity is what
separates two reads of the same table, because ``TableType`` compares equal by value.

The attribution stops at a subquery that takes a slice of its own rows, because a condition
above such a subquery cannot reach the read below it.
"""

from collections.abc import Iterator

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

# A column that needs more hops than this to reach a real table is either a resolver bug or a
# cycle. Give up instead of looping.
_MAX_COLUMN_HOPS = 32


@frozen(eq=False)
class EventsRead:
    """One read of the events table, plus the select query that reads it."""

    select: ast.SelectQuery
    table_type: ast.TableType


def find_events_reads(node: ast.AST) -> list[EventsRead]:
    collector = _EventsReadCollector()
    collector.visit(node)
    return collector.reads


def collect_conditions(node: ast.AST, read: EventsRead) -> list[ast.Expr]:
    """Top-level AND terms of every ``where`` and ``prewhere`` that constrains ``read``.

    A term from an enclosing query counts, because ClickHouse pushes a condition on a
    subquery's or a view's column down into the read. It stops counting where that push
    stops: a subquery with its own ``LIMIT`` picks which rows to hand up before the outer
    condition sees them, so the read below it still produced everything.
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
    resolved = resolve_to_table_column(expr.type)
    if resolved is None:
        return False
    table_type, name = resolved
    return name == column and table_type is read.table_type


def contains_column_of(expr: ast.Expr, read: EventsRead, column: str) -> bool:
    finder = _ColumnFinder(read=read, column=column)
    finder.visit(expr)
    return finder.found


def resolve_to_table_column(type_: ast.Type | None) -> tuple[ast.TableType, str] | None:
    """Follow a field's type down to the database table column it exports, or ``None``.

    A view or subquery column is a ``FieldType`` on that select's type; its own type is the
    expression the select exported, which may again be a column of a deeper select.
    """
    for _ in range(_MAX_COLUMN_HOPS):
        while isinstance(type_, ast.FieldAliasType):
            type_ = type_.type
        if not isinstance(type_, ast.FieldType):
            return None
        table_type = _unwrap_table_alias(type_.table_type)
        if isinstance(table_type, ast.TableType):
            return table_type, type_.name
        select_type = _select_type_of(table_type)
        if select_type is None:
            return None
        column_type = _exported_column(select_type, type_.name)
        if column_type is None:
            return None
        type_ = column_type
    return None


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


def _exported_column(select_type: ast.SelectQueryType | ast.SelectSetQueryType, name: str) -> ast.Type | None:
    column = select_type.columns.get(name)
    if column is not None:
        return column
    # A set query exports the columns of its first branch when it has none of its own.
    if isinstance(select_type, ast.SelectSetQueryType) and select_type.types:
        return _exported_column(select_type.types[0], name)
    return None


def _slices_rows(select: ast.SelectQuery) -> bool:
    """Whether this select picks which of its rows to keep, so a condition applied above it
    cannot reach the read below.

    ``LIMIT``, ``OFFSET`` and ``LIMIT BY`` all do: the rows come in the select's own order,
    and filtering earlier would keep different ones. The outermost select always carries the
    query limit, which costs nothing here because no condition sits above it.
    """
    return select.limit is not None or select.offset is not None or select.limit_by is not None


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
    """Every top-level AND term with the select query that holds it, plus each select's
    enclosing one, so a term can be matched to the reads it reaches."""

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
