"""Digest of the data a HogQL query reads.

Two queries share a read signature when they read the same tables and, on the events table, the same
day-rounded ``timestamp`` bounds and the same event names. The events table is sorted by team, then day, then
event name, so those conditions decide which part of the table a query reads. Every other filter is ignored,
because it is evaluated on rows inside that part. Bounds are rounded to the day so that two charts refreshed a
few minutes apart, whose ranges differ only in the time of day, still match.

Each SELECT is read in its own scope: projected aliases and scalar CTEs are expanded before conditions are
matched, filters applied outside a subquery or CTE reach the read inside it, each events source in FROM gets its
own read, and a CTE body counts only when something reads from it.

A ``timestamp`` or ``event`` condition in a form this module does not recognize is hashed into the signature
instead of dropped. Dropping it would report two queries with different relative windows as the same read.

The HogQL executor emits it as the ``read_signature`` query tag, which ClickHouse records in ``log_comment``.
Grouping the query log by it, within one dashboard load, shows how much work separate queries repeat over the
same data.
"""

import json
import hashlib
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

_EVENTS_TABLE = "events"
_EVENTS_TABLE_CHAINS = (["events"], ["posthog", "events"])
_TIMESTAMP_FIELD = "timestamp"
_EVENT_FIELD = "event"

_LOWER_BOUND_OPS = frozenset({ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq})
_UPPER_BOUND_OPS = frozenset({ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq})

type _Query = ast.SelectQuery | ast.SelectSetQuery

# This runs after the compilation deadline lifts, and alias chains can grow exponentially when expanded.
_WORK_BUDGET = 50_000


class _BudgetExceeded(Exception):
    pass


class _Budget:
    def __init__(self, limit: int = _WORK_BUDGET) -> None:
        self.remaining = limit

    def spend(self, amount: int = 1) -> None:
        self.remaining -= amount
        if self.remaining < 0:
            raise _BudgetExceeded


def _digest(text: str, length: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


def _opaque(expr: ast.Expr) -> str:
    # Source positions and resolved types differ between two parses of the same text, so they are cleared
    # before the expression is hashed.
    return "?" + _digest(repr(clone_expr(expr, clear_types=True, clear_locations=True)), 8)


def _day(value: object, timezone: str | None = None) -> str | None:
    """The calendar day of a bound. A day known in UTC ends in "Z", so it never matches a day in an unknown zone."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None and timezone is not None:
            value = value.replace(tzinfo=ZoneInfo(timezone))
        if value.tzinfo is not None:
            return value.astimezone(UTC).date().isoformat() + "Z"
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _bound(expr: ast.Expr) -> str:
    timezone: str | None = None
    while isinstance(expr, ast.Call) and expr.args:
        name = expr.name.lower()
        if name == "assumenotnull" and len(expr.args) == 1:
            expr = expr.args[0]
            continue
        timezone_index = {"todatetime": 1, "todatetime64": 2}.get(name)
        if timezone_index is None or len(expr.args) > timezone_index + 1:
            break
        if len(expr.args) == timezone_index + 1:
            argument = expr.args[timezone_index]
            if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                break
            timezone = argument.value
        expr = expr.args[0]
    if isinstance(expr, ast.Constant):
        try:
            day = _day(expr.value, timezone)
        except (KeyError, ValueError):
            day = None
        if day is not None:
            return day
    return _opaque(expr)


def _string_constants(expr: ast.Expr) -> set[str] | None:
    if isinstance(expr, ast.Constant):
        return {expr.value} if isinstance(expr.value, str) else None
    if isinstance(expr, ast.Tuple | ast.Array):
        names: set[str] = set()
        for item in expr.exprs:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            names.add(item.value)
        return names
    return None


def _conjuncts(expr: ast.Expr | None) -> list[ast.Expr]:
    if expr is None:
        return []
    if isinstance(expr, ast.And):
        return [conjunct for item in expr.exprs for conjunct in _conjuncts(item)]
    return [expr]


def _field_chain(expr: ast.Expr) -> list[str] | None:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field) or not all(isinstance(part, str) for part in expr.chain):
        return None
    return [str(part) for part in expr.chain]


class _ExpandNames(CloningVisitor):
    """Replace projected aliases and scalar CTEs with their definitions, leaving nested queries to their own scope."""

    def __init__(self, names: dict[str, ast.Expr], budget: _Budget) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.names = names
        self.budget = budget
        self.expanding: set[str] = set()

    def visit(self, node: ast.AST | None) -> ast.Expr:
        self.budget.spend()
        return super().visit(node)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        name = node.chain[0] if len(node.chain) == 1 else None
        if isinstance(name, str) and name in self.names and name not in self.expanding:
            self.expanding.add(name)
            try:
                return self.visit(self.names[name])
            finally:
                self.expanding.discard(name)
        return super().visit_field(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.Expr:
        return clone_expr(node, clear_types=True, clear_locations=True)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.Expr:
        return clone_expr(node, clear_types=True, clear_locations=True)


class _NestedQueries(TraversingVisitor):
    """Collect the queries nested in an expression without descending into them."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[_Query] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.found.append(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.found.append(node)


class _WindowFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None


def _blocks_pushed_filters(node: ast.SelectQuery) -> bool:
    # A filter outside a LIMIT, an ARRAY JOIN or a window function does not narrow the rows read inside it.
    if node.limit is not None or node.array_join_op is not None:
        return True
    finder = _WindowFinder()
    for expr in node.select:
        finder.visit(expr)
    return finder.found


class _Source:
    """One entry of a FROM chain: the events table, another table, or a subquery or CTE read in its own scope."""

    def __init__(self, alias: str, table: str | None = None, query: _Query | None = None) -> None:
        self.alias = alias
        self.table = table
        self.query = query


class _ReadCollector:
    def __init__(self) -> None:
        self.reads: set[str] = set()
        self.budget = _Budget()
        self._reading_ctes: set[int] = set()
        self._read_scopes: set[tuple[int, tuple[str, ...]]] = set()

    def query(self, node: _Query, ctes: dict[str, ast.CTE], pushed: list[ast.Expr]) -> None:
        if isinstance(node, ast.SelectQuery):
            self.select(node, ctes, pushed)
            return
        # The first query's CTEs are visible to every branch of a set query.
        initial = node.initial_select_query
        branch_ctes = {**ctes, **(initial.ctes or {})} if isinstance(initial, ast.SelectQuery) else ctes
        self.query(initial, branch_ctes, pushed)
        for subsequent in node.subsequent_select_queries:
            self.query(subsequent.select_query, branch_ctes, pushed)

    def select(self, node: ast.SelectQuery, outer_ctes: dict[str, ast.CTE], pushed: list[ast.Expr]) -> None:
        if pushed and _blocks_pushed_filters(node):
            pushed = []
        scope = (id(node), tuple(repr(condition) for condition in pushed))
        if scope in self._read_scopes:
            return
        self._read_scopes.add(scope)
        self.budget.spend()
        ctes = {**outer_ctes, **(node.ctes or {})}
        names: dict[str, ast.Expr] = {
            name: cte.expr for name, cte in ctes.items() if cte.cte_type == "column" and cte.expr is not None
        }
        for selected in node.select:
            if isinstance(selected, ast.Alias):
                names.setdefault(selected.alias, selected.expr)
        expand = _ExpandNames(names, self.budget)

        sources: list[_Source] = []
        conditions: list[tuple[ast.Expr, frozenset[str] | None]] = [
            (condition, None) for condition in [*pushed, *_conjuncts(node.where), *_conjuncts(node.prewhere)]
        ]
        join = node.select_from
        while join is not None:
            preceding = frozenset(source.alias for source in sources)
            source = self._source(join, ctes)
            if source is not None:
                sources.append(source)
            if join.constraint is not None:
                narrows = _join_narrows(join.join_type, source.alias if source is not None else None, preceding)
                conditions.extend((condition, narrows) for condition in _conjuncts(join.constraint.expr))
            join = join.next_join
        conjuncts = [(expand.visit(condition), narrows) for condition, narrows in conditions]

        for source in sources:
            applicable = [conjunct for conjunct, narrows in conjuncts if narrows is None or source.alias in narrows]
            if source.table == _EVENTS_TABLE:
                self.reads.add(self._describe_events_read(source, sources, applicable))
            elif source.table is not None:
                self.reads.add(source.table)
            elif source.query is not None and id(source.query) not in self._reading_ctes:
                # A recursive CTE reads itself, which adds nothing to the read already being collected.
                self._reading_ctes.add(id(source.query))
                try:
                    relevant = [conjunct for conjunct in applicable if self._reads_only(conjunct, source, sources)]
                    self.query(source.query, ctes, self._pushable(source, relevant))
                finally:
                    self._reading_ctes.discard(id(source.query))

        self._nested(node, [conjunct for conjunct, _ in conjuncts], ctes, expand)

    def _source(self, join: ast.JoinExpr, ctes: dict[str, ast.CTE]) -> _Source | None:
        table = join.table
        if isinstance(table, ast.SelectQuery | ast.SelectSetQuery):
            return _Source(alias=join.alias or "", query=table)
        if not isinstance(table, ast.Field):
            return None
        chain = [str(part) for part in table.chain]
        if len(chain) == 1 and chain[0] in ctes:
            cte = ctes[chain[0]]
            if cte.cte_type == "subquery" and isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery):
                return _Source(alias=join.alias or chain[0], query=cte.expr)
            return None
        if chain in _EVENTS_TABLE_CHAINS:
            return _Source(alias=join.alias or chain[-1], table=_EVENTS_TABLE)
        return _Source(alias=join.alias or chain[-1], table=".".join(chain))

    @staticmethod
    def _owner(chain: list[str], sources: list[_Source]) -> _Source | None:
        """The source a field belongs to. An unqualified field belongs to the only source, or to none."""
        if len(chain) == 1:
            return sources[0] if len(sources) == 1 else None
        return next((source for source in sources if source.alias == chain[0]), None)

    def _reads_only(self, conjunct: ast.Expr, source: _Source, sources: list[_Source]) -> bool:
        fields = _FieldChains()
        fields.visit(conjunct)
        if not fields.chains:
            return False
        return all(len(chain) <= 2 and self._owner(chain, sources) is source for chain in fields.chains)

    @staticmethod
    def _pushable(source: _Source, relevant: list[ast.Expr]) -> list[ast.Expr]:
        return [_Unqualify(source.alias).visit(conjunct) for conjunct in relevant]

    def _is_events_field(self, expr: ast.Expr, name: str, source: _Source, sources: list[_Source]) -> bool:
        chain = _field_chain(expr)
        if chain is None or not 1 <= len(chain) <= 2 or chain[-1] != name:
            return False
        # An unqualified field can belong to any events source in scope.
        return len(chain) == 1 or chain[0] == source.alias

    def _event_names(self, expr: ast.Expr, source: _Source, sources: list[_Source]) -> set[str] | None:
        if isinstance(expr, ast.Or):
            names: set[str] = set()
            for branch in expr.exprs:
                branch_names = self._event_names(branch, source, sources)
                if branch_names is None:
                    return None
                names |= branch_names
            return names
        if not isinstance(expr, ast.CompareOperation):
            return None
        if expr.op == ast.CompareOperationOp.Eq:
            for field_side, value_side in ((expr.left, expr.right), (expr.right, expr.left)):
                if self._is_events_field(field_side, _EVENT_FIELD, source, sources) and isinstance(
                    value_side, ast.Constant
                ):
                    return _string_constants(value_side)
            return None
        if expr.op == ast.CompareOperationOp.In and self._is_events_field(expr.left, _EVENT_FIELD, source, sources):
            return _string_constants(expr.right)
        return None

    def _describe_events_read(self, source: _Source, sources: list[_Source], conjuncts: list[ast.Expr]) -> str:
        lower: set[str] = set()
        upper: set[str] = set()
        # One entry for each condition, because two conditions on the event name narrow each other.
        event_filters: set[str] = set()
        unrecognized: set[str] = set()

        for conjunct in conjuncts:
            if (
                isinstance(conjunct, ast.BetweenExpr)
                and not conjunct.negated
                and self._is_events_field(conjunct.expr, _TIMESTAMP_FIELD, source, sources)
            ):
                lower.add(_bound(conjunct.low))
                upper.add(_bound(conjunct.high))
                continue

            if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _LOWER_BOUND_OPS | _UPPER_BOUND_OPS:
                field_on_left = self._is_events_field(conjunct.left, _TIMESTAMP_FIELD, source, sources)
                if field_on_left or self._is_events_field(conjunct.right, _TIMESTAMP_FIELD, source, sources):
                    # `timestamp >= X` and `X <= timestamp` are the same lower bound.
                    is_lower = (conjunct.op in _LOWER_BOUND_OPS) == field_on_left
                    (lower if is_lower else upper).add(_bound(conjunct.right if field_on_left else conjunct.left))
                    continue

            names = self._event_names(conjunct, source, sources)
            if names is not None:
                event_filters.add(json.dumps(sorted(names), separators=(",", ":")))
                continue

            fields = _FieldChains()
            fields.visit(conjunct)
            if any(
                self._is_events_field(ast.Field(chain=list(chain)), name, source, sources)
                for chain in fields.chains
                for name in (_TIMESTAMP_FIELD, _EVENT_FIELD)
            ):
                unrecognized.add(_opaque(conjunct))

        return "|".join(
            [
                _EVENTS_TABLE,
                ",".join(sorted(lower)),
                ",".join(sorted(upper)),
                ";".join(sorted(event_filters)) or "*",
                ",".join(sorted(unrecognized)),
            ]
        )

    def _nested(
        self, node: ast.SelectQuery, conjuncts: list[ast.Expr], ctes: dict[str, ast.CTE], expand: _ExpandNames
    ) -> None:
        # Expanding the projection reaches scalar CTE subqueries referenced only there.
        finder = _NestedQueries()
        for expr in [*node.select, *(node.group_by or []), *(node.order_by or [])]:
            finder.visit(expand.visit(expr))
        for expr in conjuncts:
            finder.visit(expr)
        if node.having is not None:
            finder.visit(expand.visit(node.having))
        for nested in finder.found:
            self.query(nested, ctes, [])


def _join_narrows(join_type: str | None, joined: str | None, preceding: frozenset[str]) -> frozenset[str] | None:
    """The aliases an ON condition can narrow. An outer join keeps every row of its preserved side."""
    kind = (join_type or "").upper()
    if "FULL" in kind:
        return frozenset()
    if "LEFT" in kind:
        return frozenset({joined}) if joined is not None else frozenset()
    if "RIGHT" in kind:
        return preceding
    return None


class _FieldChains(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.chains: list[list[str]] = []

    def visit_field(self, node: ast.Field) -> None:
        self.chains.append([str(part) for part in node.chain])

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None


class _Unqualify(CloningVisitor):
    """Rewrite `alias.column` as `column`, the name of the subquery's output."""

    def __init__(self, alias: str) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.alias = alias

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if len(node.chain) == 2 and node.chain[0] == self.alias:
            return ast.Field(chain=[node.chain[1]])
        return super().visit_field(node)


def read_signature(node: _Query) -> str | None:
    """Return a 16-hex-character digest of what the query reads, or None when it reads no table."""
    collector = _ReadCollector()
    try:
        collector.query(node, {}, [])
    except _BudgetExceeded:
        return None
    if not collector.reads:
        return None
    return _digest("\x1f".join(sorted(collector.reads)), 16)
