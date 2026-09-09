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
    return any(
        name == column and table_type is read.table_type for table_type, name in resolve_to_table_columns(expr.type)
    )


def contains_column_of(expr: ast.Expr, read: EventsRead, column: str) -> bool:
    finder = _ColumnFinder(read=read, column=column)
    finder.visit(expr)
    return finder.found


def depends_on_data(expr: ast.Expr) -> bool:
    """Whether the value of ``expr`` comes from the data, through a column or a subquery.

    Anything else is fixed when the query is planned, whatever shape it has.
    """
    finder = _DataReferenceFinder()
    finder.visit(expr)
    return finder.found


def resolve_to_table_columns(type_: ast.Type | None) -> list[tuple[ast.TableType, str]]:
    """Follow a field's type down to the database table columns it exports.

    A view or subquery column is a ``FieldType`` on that select's type; its own type is the
    expression the select exported, which may again be a column of a deeper select. A set query
    exports one column per branch, and a condition on it constrains every branch, so the walk
    forks there and can reach more than one table.
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
            resolved.append((table_type, current.name))
            continue
        select_type = _select_type_of(table_type)
        if select_type is None:
            continue
        pending.extend((column, hops + 1) for column in _exported_columns(select_type, current.name))

    return resolved


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


class _DataReferenceFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = True

    def visit_property_access(self, node: ast.PropertyAccess) -> None:
        self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.found = True

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.found = True


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
