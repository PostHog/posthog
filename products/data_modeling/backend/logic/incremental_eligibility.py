"""Decide whether a saved query can be materialized incrementally, and say why not.

Runs on the parsed AST alone, so it is cheap enough for the SQL editor's validation debounce and
needs no ClickHouse round trip. The point is to fail at definition time with a message naming the
construct, rather than at run time with a table that is quietly wrong.

The rule that does most of the work: when the query aggregates, the incremental key must be one of
the grouping keys and the unique key must cover all of them. That makes every output row belong to
exactly one bucket, and every touched bucket get recomputed from its source rows in full. Which in
turn means *any* aggregate is safe here, including the non-associative ones (exact percentiles,
count(DISTINCT), float sum) that Snowflake, Redshift, BigQuery and Databricks all have to reject.
They have to reject them because they combine partial aggregates across refreshes; we never do.
"""

from dataclasses import dataclass, field
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.property import has_aggregation
from posthog.hogql.visitor import TraversingVisitor, clear_locations

from products.data_modeling.backend.logic.incremental import IncrementalConfig
from products.data_modeling.backend.logic.incremental_filter import find_key_expression

# Non-deterministic calls make a window irreproducible: two runs over the same window can disagree,
# so a re-run silently rewrites rows. Warned rather than blocked, because a `now()` in a filter is
# common and usually harmless, and blocking it would refuse a lot of reasonable models.
NON_DETERMINISTIC_FUNCTIONS = {
    "now",
    "now64",
    "today",
    "yesterday",
    "rand",
    "rand32",
    "rand64",
    "randcanonical",
    "generateuuidv4",
    "generateuuidv7",
}

SET_OPERATORS_BLOCKING_INCREMENTAL = {"EXCEPT", "INTERSECT"}


@dataclass(frozen=True, kw_only=True)
class EligibilityResult:
    eligible: bool
    key_candidates: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_incremental_eligibility(
    query: str,
    config: Optional[IncrementalConfig],
    *,
    column_types: Optional[dict[str, str]] = None,
) -> EligibilityResult:
    """``column_types`` is the saved query's stored ClickHouse types, used only to catch a nullable
    unique key. Omit it and that check is skipped; the runtime guard still catches it."""
    try:
        node = parse_select(query)
    except (ExposedHogQLError, ValueError) as err:
        return EligibilityResult(eligible=False, blockers=[f"This query could not be parsed: {err}"])

    selects = _leaf_selects(node)
    key_candidates = _key_candidates(selects)

    blockers: list[str] = []
    warnings: list[str] = []

    _check_set_operators(node, blockers)
    for select in selects:
        _check_shape(select, blockers)

    if config is None:
        # Editor preflight: no config chosen yet, so report only what is true of the query itself.
        _check_determinism(node, warnings)
        return EligibilityResult(
            eligible=not blockers,
            key_candidates=key_candidates,
            blockers=blockers,
            warnings=warnings,
        )

    for select in selects:
        _check_key(select, config, blockers, warnings)
        _check_unique_key(select, config, blockers)

    _check_nullable_unique_key(config, column_types, blockers)
    _check_determinism(node, warnings)

    return EligibilityResult(
        eligible=not blockers,
        key_candidates=key_candidates,
        blockers=blockers,
        warnings=warnings,
    )


def _leaf_selects(node: ast.SelectQuery | ast.SelectSetQuery) -> list[ast.SelectQuery]:
    """Every branch that contributes rows. A union branch that skips the filter would rescan all of
    history, so each one is checked independently."""
    if isinstance(node, ast.SelectQuery):
        return [node]
    selects: list[ast.SelectQuery] = []
    for branch in node.select_queries():
        selects.extend(_leaf_selects(branch))
    return selects


def _key_candidates(selects: list[ast.SelectQuery]) -> list[str]:
    """Output columns the user could pick as an incremental key: named, and not aggregates.

    Intersected across union branches, since a key only works if every branch produces it.
    """
    per_branch: list[set[str]] = []
    for select in selects:
        names: set[str] = set()
        for item in select.select:
            name = _output_name(item)
            if name is None:
                continue
            expr = item.expr if isinstance(item, ast.Alias) else item
            if not has_aggregation(expr):
                names.add(name)
        per_branch.append(names)

    if not per_branch:
        return []
    common = set.intersection(*per_branch)
    # Preserve the first branch's SELECT order rather than set order, so the picker reads like the query.
    ordered = [name for item in selects[0].select if (name := _output_name(item)) is not None]
    return [name for name in dict.fromkeys(ordered) if name in common]


def _output_name(item: ast.Expr) -> Optional[str]:
    if isinstance(item, ast.Alias):
        return item.alias
    if isinstance(item, ast.Field) and item.chain:
        return str(item.chain[-1])
    return None


def _output_names(select: ast.SelectQuery) -> set[str]:
    return {name for item in select.select if (name := _output_name(item)) is not None}


def _check_set_operators(node: ast.SelectQuery | ast.SelectSetQuery, blockers: list[str]) -> None:
    if not isinstance(node, ast.SelectSetQuery):
        return
    for set_node in node.subsequent_select_queries:
        operator = str(set_node.set_operator).upper()
        if any(banned in operator for banned in SET_OPERATORS_BLOCKING_INCREMENTAL):
            blockers.append(
                f"{operator} cannot be incremental. Removing a row on either side can add or "
                "remove output rows anywhere, so a window cannot be recomputed on its own."
            )
    for branch in node.select_queries():
        _check_set_operators(branch, blockers)


def _check_shape(select: ast.SelectQuery, blockers: list[str]) -> None:
    if select.limit is not None:
        blockers.append("LIMIT cannot be incremental. A top-N within one window is not a top-N overall.")
    if select.limit_by is not None:
        blockers.append("LIMIT BY cannot be incremental. A per-window limit is not a limit overall.")
    if select.order_by:
        blockers.append(
            "A top-level ORDER BY has no effect on a materialized table and cannot be incremental. "
            "Sort when you query the view instead."
        )
    if select.distinct and not select.group_by:
        blockers.append(
            "SELECT DISTINCT cannot be incremental without a GROUP BY. Deduplicating one window "
            "says nothing about rows in other windows. Group by the same columns instead."
        )
    if _has_window_function(select):
        blockers.append(
            "Window functions cannot be incremental. Their frames reach across rows outside the "
            "window being recomputed."
        )
    if select.group_by_mode in ("cube", "rollup", "grouping_sets"):
        blockers.append(
            f"GROUP BY {select.group_by_mode.upper()} cannot be incremental, because one source row "
            "contributes to several output rows at different levels."
        )


def _check_key(select: ast.SelectQuery, config: IncrementalConfig, blockers: list[str], warnings: list[str]) -> None:
    key_expr = find_key_expression(select, config.incremental_key)
    if key_expr is None:
        blockers.append(
            f'"{config.incremental_key}" is not one of this query\'s output columns, so there is '
            "nothing to filter new rows on."
        )
        return

    if has_aggregation(key_expr):
        blockers.append(
            f'"{config.incremental_key}" is an aggregate, so it cannot be filtered before grouping. '
            "Pick a column the query groups by, or a plain timestamp column."
        )
        return

    if select.group_by:
        grouping = _grouping_key_names(select)
        if config.incremental_key not in grouping:
            blockers.append(
                f'"{config.incremental_key}" must be one of the GROUP BY columns. Otherwise a run '
                "would recompute only part of a group and overwrite the whole row with it."
            )

    if _key_behind_aggregate_subquery(select, config.incremental_key):
        warnings.append(
            f'"{config.incremental_key}" comes from a subquery or CTE that aggregates, so the '
            "filter cannot be pushed down to the source. Results stay correct, but each run will "
            "read as much data as a full refresh."
        )


def _check_unique_key(select: ast.SelectQuery, config: IncrementalConfig, blockers: list[str]) -> None:
    outputs = _output_names(select)
    missing = [column for column in config.unique_key if column not in outputs]
    if missing:
        blockers.append(
            f"Unique key {'columns' if len(missing) > 1 else 'column'} "
            f"{', '.join(sorted(missing))} {'are' if len(missing) > 1 else 'is'} not in the query's output."
        )
        return

    if select.group_by:
        grouping = _grouping_key_names(select)
        uncovered = sorted(grouping - set(config.unique_key))
        if uncovered:
            blockers.append(
                f"The unique key must include every GROUP BY column. Add {', '.join(uncovered)}, "
                "or rows that differ only by those columns will overwrite each other."
            )


def _check_nullable_unique_key(
    config: IncrementalConfig, column_types: Optional[dict[str, str]], blockers: list[str]
) -> None:
    """A NULL never matches an existing row, so the upsert inserts instead of updating and the
    table gains a duplicate on every run, forever, with nothing failing."""
    if not column_types:
        return
    for column in config.unique_key:
        clickhouse_type = column_types.get(column)
        if isinstance(clickhouse_type, str) and clickhouse_type.strip().lower().startswith("nullable("):
            blockers.append(
                f'Unique key column "{column}" can be null. A null key adds a duplicate row on '
                f"every run instead of updating. Wrap it in coalesce() to give it a fallback value."
            )


def _grouping_key_names(select: ast.SelectQuery) -> set[str]:
    """GROUP BY entries as output-column names.

    A grouping entry is usually a reference to a select alias (``GROUP BY day``), but it can repeat
    the expression instead (``GROUP BY toStartOfDay(timestamp)``). Match the second form back to
    its alias so both spellings behave the same.
    """
    # Locations are cleared on both sides so an inline entry matches the alias structurally,
    # rather than only when the two happen to sit at the same offsets.
    alias_by_expr = {
        repr(clear_locations(item.expr)): item.alias for item in select.select if isinstance(item, ast.Alias)
    }
    output_names = _output_names(select)

    names: set[str] = set()
    for entry in select.group_by or []:
        if isinstance(entry, ast.Field) and entry.chain and str(entry.chain[-1]) in output_names:
            names.add(str(entry.chain[-1]))
            continue
        alias = alias_by_expr.get(repr(clear_locations(entry)))
        if alias is not None:
            names.add(alias)
    return names


def _has_window_function(select: ast.SelectQuery) -> bool:
    finder = _WindowFunctionFinder()
    for item in select.select:
        finder.visit(item)
    if select.window_exprs:
        return True
    return finder.found


def _key_behind_aggregate_subquery(select: ast.SelectQuery, incremental_key: str) -> bool:
    """True when the outer query just forwards the key from an aggregating subquery or CTE.

    The injected predicate lands in the outer WHERE, and ClickHouse cannot push a predicate through
    a GROUP BY in a subquery, so the inner scan stays full-table. The run is still correct, it just
    is not cheaper, and saying so beats letting the user conclude the feature is broken.
    """
    key_expr = find_key_expression(select, incremental_key)
    if key_expr is None or not isinstance(key_expr, ast.Field):
        return False

    for source in _source_selects(select):
        if source.group_by or any(has_aggregation(item) for item in source.select):
            if incremental_key in _output_names(source):
                return True
    return False


def _source_selects(select: ast.SelectQuery) -> list[ast.SelectQuery]:
    sources: list[ast.SelectQuery] = []
    for cte in (select.ctes or {}).values():
        if isinstance(cte.expr, ast.SelectQuery):
            sources.append(cte.expr)
        elif isinstance(cte.expr, ast.SelectSetQuery):
            sources.extend(_leaf_selects(cte.expr))

    join: Optional[ast.JoinExpr] = select.select_from
    while join is not None:
        table = join.table
        if isinstance(table, ast.SelectQuery):
            sources.append(table)
        elif isinstance(table, ast.SelectSetQuery):
            sources.extend(_leaf_selects(table))
        elif isinstance(table, ast.Field) and table.chain:
            # A bare table reference may name a CTE, whose body was already collected above.
            pass
        join = join.next_join
    return sources


class _WindowFunctionFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A window function inside a subquery is that subquery's business; only the outermost
        # select's frames can reach across the window being recomputed.
        pass


class _NonDeterministicFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found: set[str] = set()

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() in NON_DETERMINISTIC_FUNCTIONS:
            self.found.add(node.name)
        super().visit_call(node)


def _check_determinism(node: ast.Expr, warnings: list[str]) -> None:
    finder = _NonDeterministicFinder()
    finder.visit(node)
    if finder.found:
        names = ", ".join(f"{name}()" for name in sorted(finder.found))
        warnings.append(
            f"{names} makes each run depend on when it happened, so re-running a window can change "
            "rows it already wrote."
        )
