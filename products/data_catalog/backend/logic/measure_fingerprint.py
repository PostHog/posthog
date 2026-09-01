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

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.dataclasses import frozen

# uniq() is approximate and uniqExact() is not. Somebody choosing between them is choosing a
# performance trade-off, not a different business number, so both collapse to uniq(). Set this to
# False to keep the two apart if real proposals show the distinction matters to reviewers.
COLLAPSE_EXACT_UNIQ = True

_EXACT_UNIQ_NAMES = frozenset({"uniqExact", "uniqCombined", "uniqHLL12", "uniqTheta"})

# A conjunct that constrains one of these columns is a time window, which is slice rather than
# identity. Resolving the query against the team database would type these exactly, but that needs a
# Team and turns this module into a database-backed one. The name test keeps it a pure function, and
# `unresolved_time_columns` reports what it matched so the guess stays auditable.
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
    }
)

_TIME_COLUMN_SUFFIXES = ("_at", "_date", "_time", "_timestamp")

# Guards against a pathological nest of subqueries. No real analyst query approaches this.
_MAX_SOURCE_DEPTH = 5


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


def extract_measures(query: str) -> list[MeasureFingerprint]:
    """Return one fingerprint per measure the query computes.

    Raises ``MeasureExtractionError`` when the text does not parse. An empty list means the query
    parsed but aggregates nothing, which is a different outcome and worth counting separately.
    """
    # Extraction and printing are both guarded. A saved query can parse and still fail to print, so
    # a scan that only guarded the parse would die on one team's query instead of skipping it.
    try:
        node = parse_select(query)
        return _measures_for(node)
    except BaseHogQLError as error:
        raise MeasureExtractionError(str(error)) from error
    except RecursionError as error:
        raise MeasureExtractionError("Query nests too deeply to parse.") from error


def _measures_for(node: ast.SelectQuery | ast.SelectSetQuery) -> list[MeasureFingerprint]:
    if isinstance(node, ast.SelectSetQuery):
        # Each branch of a union computes its own number, so each branch is its own measure.
        measures: list[MeasureFingerprint] = []
        for branch in node.select_queries():
            measures.extend(_measures_for(branch))
        return _deduplicate(measures)
    return _deduplicate(_measures_for_select(node))


def _measures_for_select(select: ast.SelectQuery) -> list[MeasureFingerprint]:
    tables, nested_filters = _collect_sources(select)
    predicate = _identity_conjuncts([select.where, *nested_filters])

    measures: list[MeasureFingerprint] = []
    for item in select.select:
        if not _contains_aggregate(item):
            continue
        measures.append(
            MeasureFingerprint(
                tables=tables,
                aggregate=_canonical_sql(item),
                predicate=predicate,
            )
        )
    return measures


def _collect_sources(select: ast.SelectQuery, depth: int = 0) -> tuple[tuple[str, ...], list[ast.Expr]]:
    """Walk the FROM chain down to base tables.

    A filter written inside a subquery constrains the same measure as one written outside it, so the
    inner WHERE clauses come back with the table names and join the outer predicate.
    """
    tables: set[str] = set()
    filters: list[ast.Expr] = []
    if depth >= _MAX_SOURCE_DEPTH:
        return (), filters

    ctes = select.ctes or {}
    join = select.select_from
    while join is not None:
        _absorb_source(join.table, ctes, depth, tables, filters)
        join = join.next_join

    return tuple(sorted(tables)), filters


def _absorb_source(
    table: ast.Expr | None,
    ctes: dict[str, ast.CTE],
    depth: int,
    tables: set[str],
    filters: list[ast.Expr],
) -> None:
    if isinstance(table, ast.Field):
        name = ".".join(str(part) for part in table.chain)
        cte = ctes.get(name)
        if cte is None:
            tables.add(name)
            return
        _absorb_source(cte.expr, ctes, depth + 1, tables, filters)
        return

    if isinstance(table, ast.SelectQuery):
        inner_tables, inner_filters = _collect_sources(table, depth + 1)
        tables.update(inner_tables)
        filters.extend(inner_filters)
        if table.where is not None:
            filters.append(table.where)
        return

    if isinstance(table, ast.SelectSetQuery):
        for branch in table.select_queries():
            _absorb_source(branch, ctes, depth + 1, tables, filters)


def _identity_conjuncts(sources: list[ast.Expr | None]) -> tuple[str, ...]:
    conjuncts: list[ast.Expr] = []
    for expr in sources:
        _flatten_and(expr, conjuncts)

    kept = {_canonical_sql(conjunct) for conjunct in conjuncts if not _constrains_time(conjunct)}
    return tuple(sorted(kept))


def _flatten_and(expr: ast.Expr | None, into: list[ast.Expr]) -> None:
    if expr is None:
        return
    if isinstance(expr, ast.And):
        for inner in expr.exprs:
            _flatten_and(inner, into)
        return
    into.append(expr)


def _constrains_time(expr: ast.Expr) -> bool:
    return any(_is_time_column(name) for name in _referenced_field_names(expr))


def _is_time_column(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TIME_COLUMN_NAMES or lowered.endswith(_TIME_COLUMN_SUFFIXES)


def unresolved_time_columns(query: str) -> list[str]:
    """Report which column names the time heuristic matched, so a reviewer can audit the guess."""
    try:
        node = parse_select(query)
    except BaseHogQLError:
        return []
    if isinstance(node, ast.SelectSetQuery):
        node = node.initial_select_query
    if not isinstance(node, ast.SelectQuery):
        return []

    _, nested = _collect_sources(node)
    conjuncts: list[ast.Expr] = []
    for expr in [node.where, *nested]:
        _flatten_and(expr, conjuncts)

    matched = {name for conjunct in conjuncts for name in _referenced_field_names(conjunct) if _is_time_column(name)}
    return sorted(matched)


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


def _referenced_field_names(expr: ast.Expr) -> list[str]:
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


class _AggregateFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name) is not None:
            self.found = True
        super().visit_call(node)


class _FieldNameCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.names: list[str] = []

    def visit_field(self, node: ast.Field) -> None:
        if node.chain:
            self.names.append(str(node.chain[-1]))


class _AggregateNormalizer(CloningVisitor):
    """Print an expression so that equivalent spellings produce one string.

    Aliases disappear because a column label is presentation. Aggregates collapse onto a canonical
    spelling so ``count(DISTINCT person_id)`` and ``uniq(person_id)`` stop being two metrics.
    """

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        call = super().visit_call(node)
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

    if COLLAPSE_EXACT_UNIQ and call.name in _EXACT_UNIQ_NAMES:
        return ast.Call(name="uniq", args=list(call.args))

    return call


def _is_trivial_count_arg(arg: ast.Expr) -> bool:
    if isinstance(arg, ast.Constant):
        return True
    return isinstance(arg, ast.Field) and [str(part) for part in arg.chain] == ["*"]
