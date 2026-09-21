"""Decide whether a saved query can be materialized incrementally, and say why not.

Runs on the parsed AST — resolved against the team's HogQL schema when a database is supplied, so
``SELECT *`` checks against real columns — and needs no ClickHouse round trip, which keeps it cheap
enough for the SQL editor's validation debounce. The point is to fail at definition time with a
message naming the construct, rather than at run time with a table that is quietly wrong.

The rule that does most of the work: when the query aggregates, the incremental key must be one of
the grouping keys and the unique key must cover all of them. That makes every output row belong to
exactly one bucket, and every touched bucket get recomputed from its source rows in full. Which in
turn means *any* aggregate is safe here, including the non-associative ones (exact percentiles,
count(DISTINCT), float sum) that Snowflake, Redshift, BigQuery and Databricks all have to reject.
They have to reject them because they combine partial aggregates across refreshes; we never do.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    FloatArrayDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    StructDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.property import has_aggregation
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clear_locations, clone_expr

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

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

_CONSTANT_TYPE_LABELS: dict[type, str] = {
    ast.DateTimeType: "datetime",
    ast.DateType: "date",
    ast.IntegerType: "integer",
    ast.DecimalType: "decimal",
    ast.FloatType: "float",
    ast.StringType: "string",
    ast.StringJSONType: "json",
    ast.StringArrayType: "array",
    ast.UUIDType: "uuid",
    ast.BooleanType: "boolean",
    ast.ArrayType: "array",
    ast.TupleType: "tuple",
    ast.MapType: "map",
    ast.IntervalType: "interval",
    ast.AggregateStateType: "aggregate",
}

# Types that cannot serve as a watermark. Booleans, arrays, maps, and JSON have no "highest value
# so far" for the next run to start from. Strings are excluded as a product call: lexicographic
# order is arbitrary for most string columns, so offering them invites keys that silently miss
# rows. UUIDs are excluded because only v7 is time-ordered and the column type cannot tell
# versions apart — a v4 watermark jumps around and misses rows. Unknown types stay, since a wrong
# exclusion hides a working column while a wrong inclusion just fails validation.
_NON_KEY_TYPE_LABELS = {
    "boolean",
    "array",
    "tuple",
    "map",
    "interval",
    "aggregate",
    "string",
    "uuid",
    "json",
    "struct",
}

# The unique key has looser needs: it only has to identify a row, so any equatable type works —
# and it MUST admit strings and booleans, since every GROUP BY column (event names, ids, flags)
# has to be coverable. UUIDs qualify too: equality is exactly what they are for.
_NON_UNIQUE_KEY_TYPE_LABELS = {"array", "tuple", "map", "interval", "aggregate", "json", "struct"}


@dataclass(frozen=True, kw_only=True)
class EligibilityResult:
    eligible: bool
    key_candidates: list[str] = field(default_factory=list)
    # Columns the unique key may be built from: a superset of key_candidates, since identifying a
    # row only needs equality while the incremental key needs an advancing order.
    unique_key_candidates: list[str] = field(default_factory=list)
    # Coarse type per candidate, for the picker's type tags. Missing entry: type unknown.
    key_candidate_types: dict[str, str] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_incremental_eligibility(
    query: str,
    config: Optional[IncrementalConfig],
    *,
    column_types: Optional[dict[str, str]] = None,
    database: Optional["Database"] = None,
) -> EligibilityResult:
    """``column_types`` is the saved query's stored ClickHouse types, used only to catch a nullable
    unique key. Omit it and that check is skipped; the runtime guard still catches it.

    ``database`` is the team's HogQL schema. With it, ``SELECT *`` is expanded to real columns, so
    the key candidates are pickable names and a config naming an expanded column passes. Without it
    (or when the query does not resolve against it), the raw AST is checked as-is."""
    try:
        node = parse_select(query)
    except (ExposedHogQLError, ValueError) as err:
        return EligibilityResult(eligible=False, blockers=[f"This query could not be parsed: {err}"])

    raw_selects = _leaf_selects(node)
    resolved_selects = _resolved_selects(node, database)
    selects = resolved_selects if resolved_selects is not None else raw_selects
    all_candidates = _key_candidates(selects)
    key_candidate_types = (
        _key_candidate_types(resolved_selects, database) if resolved_selects is not None and database else {}
    )
    # A column whose type cannot serve would only ever fail validation, so don't offer it.
    key_candidates = [name for name in all_candidates if key_candidate_types.get(name) not in _NON_KEY_TYPE_LABELS]
    unique_key_candidates = [
        name for name in all_candidates if key_candidate_types.get(name) not in _NON_UNIQUE_KEY_TYPE_LABELS
    ]

    blockers: list[str] = []
    warnings: list[str] = []

    _check_set_operators(node, blockers)
    # Shape is purely structural, so the raw AST is enough — no need for the resolved copy.
    for select in raw_selects:
        _check_shape(select, blockers)
        _check_nested_shapes(select, blockers)

    if config is None:
        # Editor preflight: no config chosen yet, so report only what is true of the query itself.
        _check_determinism(node, warnings)
        return EligibilityResult(
            eligible=not blockers,
            key_candidates=key_candidates,
            unique_key_candidates=unique_key_candidates,
            key_candidate_types=key_candidate_types,
            blockers=_unique(blockers),
            warnings=_unique(warnings),
        )

    for select in selects:
        _check_key(select, config, blockers, warnings)
        _check_unique_key(select, config, blockers)

    _check_nullable_unique_key(config, column_types, blockers)
    _check_determinism(node, warnings)

    return EligibilityResult(
        eligible=not blockers,
        key_candidates=key_candidates,
        unique_key_candidates=unique_key_candidates,
        key_candidate_types=key_candidate_types,
        blockers=_unique(blockers),
        warnings=_unique(warnings),
    )


def _unique(messages: list[str]) -> list[str]:
    """Recursing into every union branch, CTE and subquery can trip the same blocker several times;
    the user needs to read it once."""
    return list(dict.fromkeys(messages))


def _resolved_selects(
    node: ast.SelectQuery | ast.SelectSetQuery, database: Optional["Database"]
) -> Optional[list[ast.SelectQuery]]:
    """The query's leaf selects with types resolved, which expands ``*`` to the table's columns.

    Resolution can fail for reasons eligibility should not care about (an unknown table, a bad
    column — full validation reports those with a better message), so failure means falling back to
    the unresolved AST rather than surfacing an error.

    A column that is an aggregate one level down (``SELECT *`` over an aggregating subquery)
    expands to a plain field carrying no aggregate marker, so it stays a key candidate — exactly as
    it already does when the user writes that column out by hand.
    """
    if database is None:
        return None
    context = HogQLContext(team_id=None, database=database, enable_select_queries=True)
    try:
        # Resolve a private copy: a failure partway through could leave types on shared subtrees,
        # and the fallback path needs `node` pristine.
        resolved = resolve_types(clone_expr(node), context, dialect="hogql")
    except Exception:
        return None
    return _leaf_selects(resolved)


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


# Ordered because of subclassing: MapStringDatabaseField extends StringJSONDatabaseField, and the
# json/array string variants must be recognized before plain StringDatabaseField.
_DATABASE_FIELD_LABELS: list[tuple[type, str]] = [
    (DateTimeDatabaseField, "datetime"),
    (DateDatabaseField, "date"),
    (IntegerDatabaseField, "integer"),
    (DecimalDatabaseField, "decimal"),
    (FloatDatabaseField, "float"),
    (BooleanDatabaseField, "boolean"),
    (UUIDDatabaseField, "uuid"),
    (StringJSONDatabaseField, "json"),
    (StringArrayDatabaseField, "array"),
    (FloatArrayDatabaseField, "array"),
    (StructDatabaseField, "struct"),
    (StringDatabaseField, "string"),
]


def _database_field_label(database_field: object) -> Optional[str]:
    for field_class, label in _DATABASE_FIELD_LABELS:
        if isinstance(database_field, field_class):
            return label
    return None


def _expression_field_label(field_type: ast.ExpressionFieldType, context: HogQLContext) -> Optional[str]:
    """Schema-level computed columns (events.person_id, the error tracking issue_* joins) keep
    their inner expression untyped in the hogql dialect, so type it here the way the execution
    dialects do: resolve a copy scoped to the field's own table."""
    table_type = field_type.table_type
    while isinstance(table_type, ast.VirtualTableType):
        table_type = table_type.table_type
    scope = ast.SelectQueryType(tables={field_type.name: table_type})
    try:
        resolved = resolve_types(clone_expr(field_type.expr), context, dialect="hogql", scopes=[scope])
        if resolved.type is None:
            return None
        return _CONSTANT_TYPE_LABELS.get(type(resolved.type.resolve_constant_type(context)))
    except Exception:
        return None


def _key_candidate_types(selects: list[ast.SelectQuery], database: "Database") -> dict[str, str]:
    """Coarse type labels for the picker's type tags, from the resolved AST.

    A raw table column resolves to its schema DatabaseField, which is the reliable source; only
    computed expressions need the constant-type route. Reads the first branch only: a union whose
    branches disagree on a column's type is already a modeling problem, and the first branch is
    where the candidate order comes from too.
    """
    context = HogQLContext(team_id=None, database=database)
    labels: dict[str, str] = {}
    for item in selects[0].select:
        name = _output_name(item)
        if name is None:
            continue
        expr = item.expr if isinstance(item, ast.Alias) else item
        if expr.type is None:
            continue
        label: Optional[str] = None
        if isinstance(expr.type, ast.FieldType):
            try:
                label = _database_field_label(expr.type.resolve_database_field(context))
            except Exception:
                label = None
        elif isinstance(expr.type, ast.ExpressionFieldType):
            label = _expression_field_label(expr.type, context)
        if label is None:
            try:
                label = _CONSTANT_TYPE_LABELS.get(type(expr.type.resolve_constant_type(context)))
            except Exception:
                label = None
        if label is not None:
            labels[name] = label
    return labels


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


def _check_shape(select: ast.SelectQuery, blockers: list[str], *, nested: bool = False) -> None:
    if select.limit is not None:
        blockers.append(_row_slice_blocker("LIMIT", "A top-N within one window is not a top-N overall.", nested))
    if select.offset is not None:
        blockers.append(
            _row_slice_blocker("OFFSET", "The rows skipped within one window are not the rows skipped overall.", nested)
        )
    if select.limit_by is not None:
        blockers.append(_row_slice_blocker("LIMIT BY", "A per-window limit is not a limit overall.", nested))
    if not nested:
        # Only outer concerns. Nested, an ORDER BY without a LIMIT changes nothing (and with one,
        # the LIMIT blocker already fires); a nested DISTINCT commutes with the window filter, so
        # deduplicating before or after filtering gives the same rows.
        if select.order_by:
            blockers.append(
                "A top-level ORDER BY has no effect on a materialized table and cannot be incremental. "
                "Sort when you query the view instead."
            )
        if select.distinct and not _is_grouped(select):
            blockers.append(
                "SELECT DISTINCT cannot be incremental without a GROUP BY. Deduplicating one window "
                "says nothing about rows in other windows. Group by the same columns instead."
            )
    if select.having is not None:
        blockers.append(
            "HAVING cannot be incremental. A group can pass the condition on one run and fail it "
            "on a later one, and the upsert never deletes, so the row already written would stay "
            "forever."
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


def _row_slice_blocker(construct: str, outer_reason: str, nested: bool) -> str:
    if nested:
        article = "An" if construct[0] in "AEIOU" else "A"
        return (
            f"{article} {construct} inside a subquery or CTE cannot be incremental. Which rows it "
            "lets through changes as data arrives, so a window cannot be recomputed to the same result."
        )
    return f"{construct} cannot be incremental. {outer_reason}"


def _check_nested_shapes(select: ast.SelectQuery, blockers: list[str]) -> None:
    """Row sources feed the outer result one for one, so a shape that breaks incremental at the top
    breaks it just as well any number of levels down. Only row sources: a scalar or IN subquery in
    an expression contributes a value, not rows — its hazard is that the value drifts as data
    arrives, which holds with or without a LIMIT inside it and is the same class as ``now()``."""
    for source in _source_nodes(select):
        _check_set_operators(source, blockers)
        for leaf in _leaf_selects(source):
            _check_shape(leaf, blockers, nested=True)
            _check_nested_shapes(leaf, blockers)


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

    if _is_grouped(select):
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
    # An unexpanded star (no database to resolve against) passes every source column through, so a
    # name that is not spelled out can still be in the output. The runtime upsert fails loudly if
    # it genuinely is not.
    has_star = any(isinstance(item, ast.Field) and item.chain and str(item.chain[-1]) == "*" for item in select.select)
    missing = [column for column in config.unique_key if column not in outputs and not has_star]
    if missing:
        blockers.append(
            f"Unique key {'columns' if len(missing) > 1 else 'column'} "
            f"{', '.join(sorted(missing))} {'are' if len(missing) > 1 else 'is'} not in the query's output."
        )
        return

    if _is_grouped(select):
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


def _is_grouped(select: ast.SelectQuery) -> bool:
    """``GROUP BY ALL`` carries no explicit entries, so a check that only reads ``group_by`` would
    treat an aggregating query as ungrouped and pass every grouping rule vacuously."""
    return bool(select.group_by) or select.group_by_mode == "all"


def _grouping_key_names(select: ast.SelectQuery) -> set[str]:
    """GROUP BY entries as output-column names.

    A grouping entry is usually a reference to a select alias (``GROUP BY day``), but it can repeat
    the expression instead (``GROUP BY toStartOfDay(timestamp)``). Match the second form back to
    its alias so both spellings behave the same.

    ``GROUP BY ALL`` groups by every non-aggregate output column, which is what it expands to.
    """
    if not select.group_by and select.group_by_mode == "all":
        return {
            name
            for item in select.select
            if (name := _output_name(item)) is not None
            and not has_aggregation(item.expr if isinstance(item, ast.Alias) else item)
        }

    # Locations are cleared on both sides so an inline entry matches the alias structurally,
    # rather than only when the two happen to sit at the same offsets.
    alias_by_expr = {
        repr(clear_locations(item.expr)): item.alias for item in select.select if isinstance(item, ast.Alias)
    }
    output_names = _output_names(select)

    names: set[str] = set()
    for entry in select.group_by or []:
        # The resolver rewrites a grouping entry that names a select alias into an Alias node, so
        # on a resolved AST this is the form a plain ``GROUP BY event`` arrives in.
        if isinstance(entry, ast.Alias) and entry.alias in output_names:
            names.add(entry.alias)
            continue
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


def _source_nodes(select: ast.SelectQuery) -> list[ast.SelectQuery | ast.SelectSetQuery]:
    """The selects this one draws rows from: subquery CTEs, plus subqueries in FROM or a JOIN.

    A column CTE (``WITH (SELECT ...) AS x``) is a scalar value, not a row source, so it is
    skipped. A bare table reference in FROM may name a CTE, whose body was already collected from
    the declaration, so it needs no handling here.
    """
    sources: list[ast.SelectQuery | ast.SelectSetQuery] = []
    for cte in (select.ctes or {}).values():
        if cte.cte_type == "subquery" and isinstance(cte.expr, (ast.SelectQuery, ast.SelectSetQuery)):
            sources.append(cte.expr)

    join: Optional[ast.JoinExpr] = select.select_from
    while join is not None:
        if isinstance(join.table, (ast.SelectQuery, ast.SelectSetQuery)):
            sources.append(join.table)
        join = join.next_join
    return sources


def _source_selects(select: ast.SelectQuery) -> list[ast.SelectQuery]:
    selects: list[ast.SelectQuery] = []
    for source in _source_nodes(select):
        selects.extend(_leaf_selects(source))
    return selects


class _WindowFunctionFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # Scoped to one select: a row-source subquery gets its own shape check via the nested
        # recursion, and a scalar subquery's window only feeds a value, whose drift is the
        # non-determinism class, not a shape problem.
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
