"""Reduce a HogQL query to the measures it computes.

A metric is a measure, not a query: an aggregate over a set of tables under a filter. The grain, the
time range, the sort order and the row limit describe how somebody sliced that measure on one
occasion, so none of them enter the fingerprint. "Signups by day" and "signups by country last week"
are one metric, and only a fingerprint that drops the slice puts them in the same group. Keep the
slice and every group collapses to a single query, which defeats the usage bar that decides what is
worth proposing.

Value literals stay. ``event = 'signup_completed'`` and ``event = 'login'`` are two metrics, so
scrubbing the literal would merge them and produce a canonical definition that is silently wrong.
This module therefore over-splits on purpose. A reviewer can merge two proposals; nobody can see a
merge that already happened.
"""

from __future__ import annotations

import json
import hashlib
import dataclasses
from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.dataclasses import frozen

# Each of these counts distinct values, as uniq() does. They trade accuracy against speed in
# different ways, but they give the same business number, so all of them collapse to uniq().
_UNIQ_VARIANTS = frozenset({"uniqExact", "uniqCombined", "uniqHLL12", "uniqTheta"})

# A conjunct that constrains one of these columns is a time window, which is slice rather than
# identity. Resolving the query against the team database would type these exactly, but that needs a
# Team and turns this module into a database-backed one. The name test keeps it a pure function.
_TIME_COLUMN_NAMES = frozenset(
    {
        "timestamp",
        "time",
        "date",
        "day",
        "week",
        "month",
        "event_time",
        "event_date",
        "created_at",
        "updated_at",
        "inserted_at",
        "first_seen",
        "last_seen",
        "period_start",
        "period_end",
    }
)

_TIME_COLUMN_SUFFIXES = ("_at", "_date", "_time", "_timestamp", "_day", "_week", "_month", "_quarter", "_year")

# A comparison of a column with a call to one of these is a time window, whatever the column is called.
_TIME_CALLS = frozenset({"now", "today", "yesterday", "todate", "todatetime", "datetrunc", "date_trunc"})
_TIME_CALL_PREFIXES = ("tostartof", "tointerval", "toyyyy", "addmonths", "adddays", "addweeks", "addyears")

# These calls give a duration, not a point in time. `dateDiff('second', started_at, ended_at) > 600`
# keeps only long sessions, so the time test does not look inside them.
_DURATION_CALLS = frozenset({"datediff", "date_diff", "age"})

# Guards against a pathological nest of subqueries. No real analyst query approaches this.
_MAX_SOURCE_DEPTH = 5

# A CTE expands once for each place that reads it, so CTEs that read each other several times grow
# exponentially. Agent-written SQL does this, and the scan must not hang on one query.
_MAX_SOURCE_EXPANSIONS = 500

_COMPARISON_CALLS = frozenset({"equals", "notEquals", "greater", "greaterOrEquals", "less", "lessOrEquals"})


class MeasureExtractionError(Exception):
    """The query text could not be parsed as HogQL."""


@frozen
class MeasureFingerprint:
    """One aggregate, the tables it reads, and the filter that decides what it counts."""

    tables: tuple[str, ...]
    aggregate: str
    predicate: tuple[str, ...]

    @property
    def digest(self) -> str:
        payload = json.dumps(
            {"tables": list(self.tables), "aggregate": self.aggregate, "predicate": list(self.predicate)},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def describe(self) -> str:
        """The claim a reviewer checks. It has to read as a sentence, not as a hash."""
        source = ", ".join(self.tables) if self.tables else "an unresolved source"
        if not self.predicate:
            return f"{self.aggregate} on {source}"
        conditions = " and ".join(_infix(condition) for condition in self.predicate)
        return f"{self.aggregate} on {source} where {conditions}"


def extract_measures(query: str, placeholders: dict[str, ast.Expr] | None = None) -> list[MeasureFingerprint]:
    """Return one fingerprint per measure the query computes.

    Raises ``MeasureExtractionError`` when the text does not parse, or when the query reshapes rows
    in a way the fingerprint cannot express. An empty list means the query parsed but aggregates
    nothing, which is a different outcome and worth counting separately.
    """
    # Extraction and printing are both guarded. A saved query can parse and still fail to print, so
    # a scan that only guarded the parse would die on one team's query instead of skipping it.
    try:
        node = parse_select(query, placeholders=placeholders)
        return _measures_for(node, _Budget())
    except BaseHogQLError as error:
        raise MeasureExtractionError(str(error)) from error
    except RecursionError as error:
        raise MeasureExtractionError("Query nests too deeply to parse.") from error


class _Budget:
    """Counts source expansions in one extraction."""

    def __init__(self) -> None:
        self.remaining = _MAX_SOURCE_EXPANSIONS

    def spend(self) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            raise MeasureExtractionError("Query expands too many sources to fingerprint.")


@dataclasses.dataclass(frozen=False)
class _Sources:
    """What a walk of the FROM chain found: the base tables, the filters on them, and how they join."""

    tables: set[str] = dataclasses.field(default_factory=set)
    filters: list[ast.Expr] = dataclasses.field(default_factory=list)
    joins: set[str] = dataclasses.field(default_factory=set)


def _measures_for(node: ast.SelectQuery | ast.SelectSetQuery, budget: _Budget) -> list[MeasureFingerprint]:
    if isinstance(node, ast.SelectSetQuery):
        # Each branch of a union computes its own number, so each branch is its own measure.
        measures: list[MeasureFingerprint] = []
        for branch in node.select_queries():
            measures.extend(_measures_for(branch, budget))
        return _deduplicate(measures)
    return _deduplicate(_measures_for_select(node, budget))


def _measures_for_select(
    select: ast.SelectQuery, budget: _Budget, inherited_ctes: dict[str, ast.CTE] | None = None, depth: int = 0
) -> list[MeasureFingerprint]:
    ctes = {**(inherited_ctes or {}), **(select.ctes or {})}
    qualifiers = _own_qualifiers(select)
    aggregates = [item for item in select.select if _contains_aggregate(item)]
    if aggregates:
        # Sources are walked only when this level aggregates. A source that groups or limits rows is
        # unmeasurable under an aggregate, but it is the measure itself when the outer query only reshapes it.
        sources = _collect_sources(select, budget, ctes, depth)
        own_filters = [
            _unqualified(condition, qualifiers)
            for condition in (select.where, select.prewhere)
            if condition is not None
        ]
        predicate = tuple(sorted({*_identity_conjuncts([*own_filters, *sources.filters]), *sources.joins}))
        return [
            MeasureFingerprint(
                tables=tuple(sorted(sources.tables)),
                aggregate=_canonical_sql(_unqualified(item, qualifiers)),
                predicate=predicate,
            )
            for item in aggregates
        ]
    if depth >= _MAX_SOURCE_DEPTH:
        # Returning no measures here would report a deep query as one that aggregates nothing.
        raise MeasureExtractionError("The source chain is too deep to fingerprint.")

    # An outer query that aggregates nothing only reshapes rows a CTE or a subquery in FROM already
    # aggregated, so the measures are theirs. An outer filter on a grouping column picks the groups
    # the inner query counted, so it narrows the measure. A filter on an aggregated value or on
    # another joined source only picks which result rows to show, which is slice.
    outer_conjuncts = [
        _unqualified(conjunct, qualifiers) for conjunct in _non_time_conjuncts([select.where, select.prewhere])
    ]
    measures: list[MeasureFingerprint] = []
    join = select.select_from
    while join is not None:
        keys = _group_keys(join.table, ctes, depth + 1)
        narrowing = {_canonical_sql(conjunct) for conjunct in outer_conjuncts if set(_field_names(conjunct)) <= keys}
        measures.extend(
            dataclasses.replace(inner, predicate=tuple(sorted({*inner.predicate, *narrowing})))
            for inner in _measures_of_source(join.table, budget, ctes, depth + 1)
        )
        join = join.next_join
    return measures


def _measures_of_source(
    table: ast.Expr | None, budget: _Budget, ctes: dict[str, ast.CTE], depth: int
) -> list[MeasureFingerprint]:
    budget.spend()
    if isinstance(table, ast.Field):
        name = _dotted(table)
        cte = ctes.get(name)
        return _measures_of_source(cte.expr, budget, _cte_body_scope(ctes, name), depth) if cte is not None else []
    if isinstance(table, ast.SelectQuery):
        return _measures_for_select(table, budget, ctes, depth)
    if isinstance(table, ast.SelectSetQuery):
        return [
            measure for branch in table.select_queries() for measure in _measures_of_source(branch, budget, ctes, depth)
        ]
    return []


def _group_keys(table: ast.Expr | None, ctes: dict[str, ast.CTE], depth: int) -> frozenset[str]:
    """The output columns of a source that name the groups its aggregate counted."""
    if depth >= _MAX_SOURCE_DEPTH:
        return frozenset()
    if isinstance(table, ast.Field):
        name = _dotted(table)
        cte = ctes.get(name)
        return _group_keys(cte.expr, _cte_body_scope(ctes, name), depth) if cte is not None else frozenset()
    if isinstance(table, ast.SelectSetQuery):
        return frozenset.intersection(*(_group_keys(branch, ctes, depth) for branch in table.select_queries()))
    if not isinstance(table, ast.SelectQuery):
        return frozenset()

    if any(_contains_aggregate(item) for item in table.select):
        # Outside an aggregate, a column of an aggregating query must be in its GROUP BY.
        return frozenset(
            output for item in table.select if not _contains_aggregate(item) and (output := _output_name(item))
        )

    scope = {**ctes, **(table.ctes or {})}
    inner: set[str] = set()
    join = table.select_from
    while join is not None:
        inner |= _group_keys(join.table, scope, depth + 1)
        join = join.next_join
    exposed: set[str] = set()
    for item in table.select:
        if isinstance(item, ast.Field) and str(item.chain[-1]) == "*":
            exposed |= inner
        elif (output := _output_name(item)) is not None and set(_field_names(item)) <= inner:
            exposed.add(output)
    return frozenset(exposed)


def _output_name(item: ast.Expr) -> str | None:
    if isinstance(item, ast.Alias):
        return item.alias
    if isinstance(item, ast.Field):
        return str(item.chain[-1])
    return None


def _dotted(field: ast.Field) -> str:
    return ".".join(str(part) for part in field.chain)


def _cte_body_scope(ctes: dict[str, ast.CTE], name: str) -> dict[str, ast.CTE]:
    # HogQL resolves the body of a non-recursive CTE before the CTE is in scope. So
    # `WITH events AS (SELECT * FROM events ...)` reads the base table in its body.
    if ctes[name].recursive:
        return ctes
    return {key: cte for key, cte in ctes.items() if key != name}


def _own_qualifiers(select: ast.SelectQuery) -> frozenset[tuple[str, ...]]:
    """The prefixes that name the only source of a query.

    With one source, ``e.event`` and ``event`` read the same column, so the prefix carries no identity.
    With a join, the prefix tells the tables apart, so it stays.
    """
    source = select.select_from
    if source is None or source.next_join is not None:
        return frozenset()
    qualifiers: set[tuple[str, ...]] = set()
    if source.alias:
        qualifiers.add((source.alias,))
    if isinstance(source.table, ast.Field):
        qualifiers.add(tuple(str(part) for part in source.table.chain))
    return frozenset(qualifiers)


def _unqualified(expr: ast.Expr, qualifiers: frozenset[tuple[str, ...]]) -> ast.Expr:
    if not qualifiers:
        return expr
    return _QualifierStripper(qualifiers).visit(expr)


def _collect_sources(
    select: ast.SelectQuery, budget: _Budget, inherited_ctes: dict[str, ast.CTE] | None = None, depth: int = 0
) -> _Sources:
    """Walk the FROM chain down to base tables.

    A filter written inside a subquery constrains the same measure as one written outside it, so the
    inner WHERE clauses come back with the table names and join the outer predicate. CTEs pass down
    the whole walk, because one CTE often reads another.
    """
    found = _Sources()
    _absorb_from(select, budget, inherited_ctes or {}, depth, found)
    return found


def _absorb_from(
    select: ast.SelectQuery, budget: _Budget, inherited_ctes: dict[str, ast.CTE], depth: int, into: _Sources
) -> None:
    if depth >= _MAX_SOURCE_DEPTH:
        # Stopping here would leave out the base tables, and then different sources share one fingerprint.
        raise MeasureExtractionError("The source chain is too deep to fingerprint.")
    if select.array_join_op or select.array_join_list:
        raise MeasureExtractionError("An ARRAY JOIN repeats rows, so the query has no fingerprint.")
    ctes = {**inherited_ctes, **(select.ctes or {})}
    join = select.select_from
    while join is not None:
        if join.table_args:
            raise MeasureExtractionError("A table function makes its own rows, so the query has no fingerprint.")
        if join.sample is not None and not join.sample.samples_all_rows():
            raise MeasureExtractionError("A sampled source counts a part of the rows, so the query has no fingerprint.")
        _absorb_source(join.table, budget, ctes, depth, into)
        if join is not select.select_from:
            # An inner and a left join over the same tables count different rows, and so does a
            # different join condition.
            into.joins.add(_join_token(join))
        join = join.next_join


def _join_token(join: ast.JoinExpr) -> str:
    join_type = " ".join((join.join_type or "JOIN").upper().replace(" OUTER", "").split())
    if join_type == "JOIN":
        join_type = "INNER JOIN"
    if join.constraint is None:
        return join_type
    return f"{join_type} {join.constraint.constraint_type} {_canonical_sql(join.constraint.expr)}"


def _absorb_source(
    table: ast.Expr | None, budget: _Budget, ctes: dict[str, ast.CTE], depth: int, into: _Sources
) -> None:
    budget.spend()
    if isinstance(table, ast.Field):
        name = _dotted(table)
        cte = ctes.get(name)
        if cte is None:
            into.tables.add(name)
            return
        # The CTE's own SELECT counts the level, so naming the CTE does not count it again.
        _absorb_source(cte.expr, budget, _cte_body_scope(ctes, name), depth, into)
        return

    if isinstance(table, ast.SelectQuery):
        _reject_row_reshaping(table)
        _absorb_from(table, budget, ctes, depth + 1, into)
        qualifiers = _own_qualifiers(table)
        into.filters.extend(
            _unqualified(condition, qualifiers) for condition in (table.where, table.prewhere) if condition is not None
        )
        if (projection := _computed_columns(table, qualifiers)) is not None:
            into.joins.add(projection)
        return

    if isinstance(table, ast.SelectSetQuery):
        if any(node.set_operator != "UNION ALL" for node in table.subsequent_select_queries) or (
            table.limit is not None or table.offset is not None
        ):
            raise MeasureExtractionError("A set operation other than UNION ALL under an aggregate has no fingerprint.")
        # A row passes a UNION ALL when it passes any one branch, so the branch filters join with OR.
        # A branch with no filter lets every row through, and then the union filters nothing.
        branch_filters: list[ast.Expr] = []
        every_branch_filters = True
        for branch in table.select_queries():
            found = _Sources()
            _absorb_source(branch, budget, ctes, depth + 1, found)
            into.tables.update(found.tables)
            into.joins.update(found.joins)
            conjuncts = _non_time_conjuncts(found.filters)
            if not conjuncts:
                every_branch_filters = False
            else:
                branch_filters.append(conjuncts[0] if len(conjuncts) == 1 else ast.And(exprs=conjuncts))
        if every_branch_filters and branch_filters:
            into.filters.append(branch_filters[0] if len(branch_filters) == 1 else ast.Or(exprs=branch_filters))


def _computed_columns(select: ast.SelectQuery, qualifiers: frozenset[tuple[str, ...]]) -> str | None:
    """The columns a source computes under a new name.

    The outer aggregate reads them by that name only, so ``sum(x)`` over ``properties.a AS x`` and over
    ``properties.b AS x`` would otherwise share one fingerprint.
    """
    computed = sorted(
        f"{item.alias} = {_canonical_sql(_unqualified(item.expr, qualifiers))}"
        for item in select.select
        if isinstance(item, ast.Alias)
        and not (isinstance(item.expr, ast.Field) and str(item.expr.chain[-1]) == item.alias)
    )
    return f"COMPUTES {', '.join(computed)}" if computed else None


def _reject_row_reshaping(select: ast.SelectQuery) -> None:
    """Refuse a source that drops, merges or collapses rows before the outer aggregate sees them.

    The fingerprint keeps only tables and filters of a source, so it would describe
    ``count() FROM (SELECT DISTINCT person_id FROM events)`` as a plain event count.
    """
    if (
        select.distinct
        or select.group_by
        or select.having is not None
        or select.limit is not None
        or select.limit_by is not None
        or select.offset is not None
        or any(_contains_aggregate(item) for item in select.select)
    ):
        raise MeasureExtractionError("A source that groups, deduplicates or limits rows has no fingerprint.")


def _non_time_conjuncts(sources: Sequence[ast.Expr | None]) -> list[ast.Expr]:
    conjuncts: list[ast.Expr] = []
    for expr in sources:
        _flatten_and(expr, conjuncts)
    return [conjunct for conjunct in conjuncts if not _constrains_time(conjunct)]


def _identity_conjuncts(sources: Sequence[ast.Expr | None]) -> tuple[str, ...]:
    return tuple(sorted({_canonical_sql(conjunct) for conjunct in _non_time_conjuncts(sources)}))


def _flatten_and(expr: ast.Expr | None, into: list[ast.Expr]) -> None:
    if expr is None:
        return
    if isinstance(expr, ast.And):
        for inner in expr.exprs:
            _flatten_and(inner, into)
        return
    # The HogQL printer writes AND as an and() call, so printed and hand-written filters must split alike.
    if isinstance(expr, ast.Call) and expr.name == "and":
        for inner in expr.args:
            _flatten_and(inner, into)
        return
    into.append(expr)


def _constrains_time(expr: ast.Expr) -> bool:
    """True when the expression is only a time window, so dropping it loses no identity.

    ``event = 'signup' OR timestamp > now()`` is not a time window: it also admits every signup.
    """
    if isinstance(expr, ast.And | ast.Or):
        return all(_constrains_time(inner) for inner in expr.exprs)
    if isinstance(expr, ast.Call) and expr.name in _LOGIC_CALLS:
        return bool(expr.args) and all(_constrains_time(inner) for inner in expr.args)
    if isinstance(expr, ast.Not):
        return _constrains_time(expr.expr)
    if isinstance(expr, ast.Call) and expr.name == "not" and len(expr.args) == 1:
        return _constrains_time(expr.args[0])
    if isinstance(expr, ast.CompareOperation):
        return _compares_time(expr.left, expr.right)
    if isinstance(expr, ast.Call) and expr.name in _COMPARISON_CALLS and len(expr.args) == 2:
        return _compares_time(expr.args[0], expr.args[1])
    if isinstance(expr, ast.BetweenExpr):
        return _compares_time(expr.expr, expr.low) and _compares_time(expr.expr, expr.high)
    return _is_time_column_operand(expr)


def _compares_time(one: ast.Expr, other: ast.Expr) -> bool:
    # A relative date such as `today()` marks a time window whatever the column is called, but only
    # when the other side reads a column. A filter that merely contains `now()` somewhere is not one.
    if _is_time_column_operand(one) or _is_time_column_operand(other):
        return True
    return (_calls_time(one) and bool(_field_names(other))) or (_calls_time(other) and bool(_field_names(one)))


def _is_time_column_operand(expr: ast.Expr) -> bool:
    collector = _TimeOperandCollector()
    collector.visit(expr)
    return bool(collector.names) and all(_is_time_column(name) for name in collector.names)


def _calls_time(expr: ast.Expr) -> bool:
    collector = _TimeOperandCollector()
    collector.visit(expr)
    return any(_is_time_call(name) for name in collector.calls)


def _is_time_column(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TIME_COLUMN_NAMES or lowered.endswith(_TIME_COLUMN_SUFFIXES)


def _is_time_call(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TIME_CALLS or lowered.startswith(_TIME_CALL_PREFIXES)


def _canonical_sql(expr: ast.Expr) -> str:
    return _AggregateNormalizer().visit(expr).to_hogql()


# The HogQL printer renders `a = b` as `equals(a, b)`, which is what makes two spellings of one
# comparison collapse onto a single fingerprint. That form is hard to read, and the reviewer has to
# check the evidence sentence quickly, so display undoes it. The canonical string keeps the function
# form, and only `describe()` calls this.
_INFIX_OPERATORS = {
    "equals": "=",
    "notEquals": "!=",
    "greater": ">",
    "greaterOrEquals": ">=",
    "less": "<",
    "lessOrEquals": "<=",
    "like": "like",
    "notLike": "not like",
    "in": "in",
    "notIn": "not in",
}


def _infix(condition: str) -> str:
    for name, operator in _INFIX_OPERATORS.items():
        prefix = f"{name}("
        if not condition.startswith(prefix) or not condition.endswith(")"):
            continue
        arguments = _split_arguments(condition[len(prefix) : -1])
        if len(arguments) != 2:
            continue
        return f"{arguments[0]} {operator} {arguments[1]}"
    return condition


def _split_arguments(text: str) -> list[str]:
    """Split on commas that sit at nesting depth zero, so nested calls stay intact."""
    arguments: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []

    for character in text:
        if quote is not None:
            current.append(character)
            if character == quote:
                quote = None
            continue
        if character in "'\"":
            quote = character
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append("".join(current).strip())
            current = []
            continue
        current.append(character)

    arguments.append("".join(current).strip())
    return arguments


def _contains_aggregate(expr: ast.Expr) -> bool:
    finder = _AggregateFinder()
    finder.visit(expr)
    return finder.found


def _field_names(expr: ast.Expr) -> list[str]:
    collector = _FieldNameCollector()
    collector.visit(expr)
    return collector.names


def _deduplicate(measures: list[MeasureFingerprint]) -> list[MeasureFingerprint]:
    seen: set[str] = set()
    unique: list[MeasureFingerprint] = []
    for measure in measures:
        if measure.digest in seen:
            continue
        seen.add(measure.digest)
        unique.append(measure)
    return unique


class _ScopedVisitor(TraversingVisitor):
    """Stops at a subquery, because a subquery aggregates and filters its own rows, not the outer ones."""

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None


class _AggregateFinder(_ScopedVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name) is not None:
            self.found = True
        super().visit_call(node)


class _FieldNameCollector(_ScopedVisitor):
    def __init__(self) -> None:
        self.names: list[str] = []
        self.calls: list[str] = []

    def visit_field(self, node: ast.Field) -> None:
        if node.chain:
            self.names.append(str(node.chain[-1]))

    def visit_call(self, node: ast.Call) -> None:
        self.calls.append(node.name)
        super().visit_call(node)


class _TimeOperandCollector(_FieldNameCollector):
    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() in _DURATION_CALLS:
            return
        super().visit_call(node)


class _QualifierStripper(CloningVisitor):
    def __init__(self, qualifiers: frozenset[tuple[str, ...]]) -> None:
        super().__init__()
        self.qualifiers = qualifiers

    def visit_field(self, node: ast.Field) -> ast.Field:
        chain = [str(part) for part in node.chain]
        for qualifier in self.qualifiers:
            if len(chain) > len(qualifier) and tuple(chain[: len(qualifier)]) == qualifier:
                return ast.Field(chain=list(node.chain[len(qualifier) :]))
        return ast.Field(chain=list(node.chain))

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        return node

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        return node


_LOGIC_CALLS = frozenset({"and", "or"})
_SYMMETRIC_CALLS = frozenset({"equals", "notEquals"})
_MEMBERSHIP_CALLS = frozenset({"in", "notIn"})
_SYMMETRIC_COMPARISONS = frozenset({ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq})
_MEMBERSHIP_COMPARISONS = frozenset({ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn})


def _sorted_operands(exprs: list[ast.Expr]) -> list[ast.Expr]:
    """Order operands that can swap without changing the result. A constant goes last, so `event = 'a'` reads as written."""
    return sorted(exprs, key=lambda expr: (isinstance(expr, ast.Constant), expr.to_hogql()))


def _sorted_logic(name: str, exprs: list[ast.Expr]) -> ast.Expr:
    """One flat `and` or `or` with sorted, unique operands, because neither nesting nor order changes the result."""
    flat: list[ast.Expr] = []
    for expr in exprs:
        if isinstance(expr, ast.Call) and expr.name == name:
            flat.extend(expr.args)
        else:
            flat.append(expr)
    unique = list({expr.to_hogql(): expr for expr in flat}.values())
    return unique[0] if len(unique) == 1 else ast.Call(name=name, args=_sorted_operands(unique))


def _sorted_members(expr: ast.Expr) -> ast.Expr:
    if isinstance(expr, ast.Tuple):
        return ast.Tuple(exprs=_sorted_operands(expr.exprs))
    if isinstance(expr, ast.Array):
        return ast.Array(exprs=_sorted_operands(expr.exprs))
    return expr


class _AggregateNormalizer(CloningVisitor):
    """Print an expression so that equivalent spellings produce one string.

    Aliases disappear because a column label is presentation. Aggregates collapse onto a canonical
    spelling so ``count(DISTINCT person_id)`` and ``uniq(person_id)`` stop being two metrics.
    """

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)

    def visit_and(self, node: ast.And) -> ast.Expr:
        return _sorted_logic("and", [self.visit(expr) for expr in node.exprs])

    def visit_or(self, node: ast.Or) -> ast.Expr:
        return _sorted_logic("or", [self.visit(expr) for expr in node.exprs])

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        left, right = self.visit(node.left), self.visit(node.right)
        if node.op in _SYMMETRIC_COMPARISONS:
            left, right = _sorted_operands([left, right])
        elif node.op in _MEMBERSHIP_COMPARISONS:
            right = _sorted_members(right)
        return ast.CompareOperation(left=left, right=right, op=node.op)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        call = super().visit_call(node)
        if call.name in _LOGIC_CALLS:
            return _sorted_logic(call.name, call.args)
        if call.name in _SYMMETRIC_CALLS and len(call.args) == 2:
            return ast.Call(name=call.name, args=_sorted_operands(call.args))
        if call.name in _MEMBERSHIP_CALLS and len(call.args) == 2:
            return ast.Call(name=call.name, args=[call.args[0], _sorted_members(call.args[1])])
        return _canonical_aggregate(call)

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        """Render `{variables.x}` as a stable token instead of letting the printer reject it.

        The HogQL printer raises on an unresolved placeholder, which would abort the scan. A
        placeholder is also the one case where two runs genuinely share a measure while their values
        differ, because a saved query with a variable is one metric whatever the variable holds. The
        token keeps those runs in one group.
        """
        return ast.Constant(value=f"{{{node.field or 'placeholder'}}}")


def _canonical_aggregate(call: ast.Call) -> ast.Call:
    if find_hogql_aggregation(call.name) is None:
        return call

    if call.name == "count":
        if call.distinct and call.args:
            return ast.Call(name="uniq", args=list(call.args))
        # count(), count(*) and count(1) are one measure written three ways. count(column) is not,
        # because it skips nulls.
        if not call.args or _is_trivial_count_arg(call.args[0]):
            return ast.Call(name="count", args=[])
        return call

    if call.name in _UNIQ_VARIANTS:
        return ast.Call(name="uniq", args=list(call.args))

    return call


def _is_trivial_count_arg(arg: ast.Expr) -> bool:
    # count(NULL) counts nothing, so only a non-null constant is the same as count().
    if isinstance(arg, ast.Constant):
        return arg.value is not None
    return isinstance(arg, ast.Field) and [str(part) for part in arg.chain] == ["*"]
