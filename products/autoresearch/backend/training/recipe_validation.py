"""Server-side validation of agent-authored model recipes.

Any agent — the in-house sandbox or an external bring-your-own agent — that records
a training iteration goes through ``validate_recipe``: the iteration's feature SQL must
be a read-only ``SELECT`` that reads ``{anchors}``, keys each row as ``person_id AS
distinct_id`` (the one-row-per-person contract), and never reads the wall clock.

The ``model_class`` allowlist (``validate_model_class``) is NOT applied at recording
time — in the artifact-bundle world the agent's real model runs as arbitrary code in a
sandbox, so the recorded ``model_class`` is informational. The allowlist is enforced
where it actually matters: the legacy in-process inference path
(``inference.py``) resolves ``model_class`` via ``importlib`` (a code-execution surface)
and calls ``validate_model_class`` there before importing.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_function
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

# Classes the inference scorer is allowed to instantiate via importlib. Keep this in
# sync with the fallback/resolution logic in inference.py — never widen it to accept
# arbitrary import paths from agent input.
ALLOWED_MODEL_CLASSES: frozenset[str] = frozenset(
    {
        "sklearn.linear_model.LogisticRegression",
        "sklearn.ensemble.RandomForestClassifier",
        "sklearn.ensemble.GradientBoostingClassifier",
        "sklearn.ensemble.HistGradientBoostingClassifier",
        "xgboost.XGBClassifier",
    }
)

# Wall-clock functions bind a window to "now" instead of each anchor's cutoff_ts. At
# training time that reads past the user's T0 into the outcome window, so the holdout
# AUC is inflated by target leakage. The agent brief promises these are rejected.
# Lowercase ClickHouse names: a call is checked both by the name the agent wrote and by
# the name HogQL resolves it to, so `NOW()` and the `current_timestamp()` alias (which
# resolves to now64) are caught alongside the plain spellings.
_WALL_CLOCK_FUNCTIONS: frozenset[str] = frozenset({"now", "now64", "nowinblock", "today", "yesterday"})

_ANCHORS = "anchors"
_PERSON_ID = "person_id"
_DISTINCT_ID = "distinct_id"

# build_training_features_sql nests the feature query inside a WITH scope that defines these
# relations. They carry the label, so a feature query that reads one of them selects the outcome
# directly at training time; at inference they do not exist and the query fails.
_TRAINING_CTE_NAMES: frozenset[str] = frozenset({"user_window", "user_t0", "labeled_users", "labeled_anchors"})
# The training wrapper appends these columns to the feature rows, so a feature query that emits
# them makes the label lookup ambiguous.
_RESERVED_OUTPUT_NAMES: frozenset[str] = frozenset({"__label", "__fold"})


class RecipeValidationError(ValueError):
    """Raised when an agent-supplied recipe fails a server-side safety check."""


def validate_model_class(model_class: str) -> None:
    if model_class not in ALLOWED_MODEL_CLASSES:
        allowed = ", ".join(sorted(ALLOWED_MODEL_CLASSES))
        raise RecipeValidationError(f"model_class '{model_class}' is not allowed. Permitted classes: {allowed}.")


def validate_feature_sql(feature_sql: str) -> None:
    if not feature_sql or not feature_sql.strip():
        raise RecipeValidationError("feature_sql is required and must be a non-empty SELECT.")
    try:
        node = parse_select(feature_sql)
    except Exception as e:
        raise RecipeValidationError(f"feature_sql is not valid HogQL: {e}") from e
    if not isinstance(node, ast.SelectQuery):
        raise RecipeValidationError("feature_sql must be a single SELECT statement (no unions or set operations).")
    # The framework substitutes {anchors} with the per-user (person_id, cutoff_ts) table. The
    # parser only produces a Placeholder node for the placeholder in code position, so a
    # '{anchors}' string literal or a commented-out placeholder does not count: the query would
    # run with no per-user T0 cutoff and read the outcome window (target leakage). It has to sit
    # in the top-level FROM: behind a CTE or a derived table the anchor key can be transformed
    # and renamed back to person_id, which nothing below can trace.
    anchors_join = _top_level_anchors_join(node)
    if anchors_join is None:
        raise RecipeValidationError(
            "feature_sql must read FROM the {anchors} placeholder table in its top-level FROM "
            '(e.g. "FROM {anchors} a LEFT JOIN events e ON ..."; columns person_id, cutoff_ts) so '
            "features are cut off at each user's T0 and cannot leak the outcome window."
        )
    problem = _output_problem(node, anchors_alias=anchors_join.alias)
    if problem:
        raise RecipeValidationError(problem)
    cte_reads = _training_cte_reads(node)
    if cte_reads:
        raise RecipeValidationError(
            f"feature_sql must not reference {', '.join(sorted(cte_reads))}: the training wrapper "
            "defines those relations and they carry the label. Read the anchors through {anchors} only."
        )
    wall_clock = _wall_clock_reads(node)
    if wall_clock:
        raise RecipeValidationError(
            f"feature_sql must not read the wall clock ({', '.join(sorted(wall_clock))}). Bound every "
            "time window to fromUnixTimestamp(a.cutoff_ts) so features stop at each user's T0."
        )


class _WallClockReads(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        resolved = find_hogql_function(name)
        if name in _WALL_CLOCK_FUNCTIONS or (resolved and resolved.clickhouse_name.lower() in _WALL_CLOCK_FUNCTIONS):
            self.names.add(f"{node.name}()")
        super().visit_call(node)

    def visit_field(self, node: ast.Field) -> None:
        # A bare CURRENT_TIMESTAMP / CURRENT_DATE has no parentheses, so it parses as a field and
        # the resolver turns it into a wall-clock keyword.
        if len(node.chain) == 1 and str(node.chain[0]).lower() in ast.VALID_KEYWORD_NAMES:
            self.names.add(str(node.chain[0]))
        super().visit_field(node)


class _TrainingCteReads(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field) and node.table.chain:
            self._check(str(node.table.chain[0]))
        super().visit_join_expr(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        for name in node.ctes or {}:
            self._check(name)
        super().visit_select_query(node)

    def _check(self, name: str) -> None:
        if name.lower() in _TRAINING_CTE_NAMES:
            self.names.add(name)


def _is_anchors_placeholder(node: ast.Expr | None) -> bool:
    return isinstance(node, ast.Placeholder) and node.field == _ANCHORS


def _wall_clock_reads(node: ast.SelectQuery) -> set[str]:
    """Every wall-clock function or keyword read anywhere in the query, subqueries included."""
    visitor = _WallClockReads()
    visitor.visit(node)
    return visitor.names


def _training_cte_reads(node: ast.SelectQuery) -> set[str]:
    """Every training-wrapper relation the query reads or redefines, subqueries included."""
    visitor = _TrainingCteReads()
    visitor.visit(node)
    return visitor.names


def _top_level_anchors_join(node: ast.SelectQuery) -> ast.JoinExpr | None:
    """The top-level FROM entry whose table is ``{anchors}``, or None when it is not there."""
    join = node.select_from
    while join is not None:
        if _is_anchors_placeholder(join.table):
            return join
        join = join.next_join
    return None


def _output_problem(node: ast.SelectQuery, *, anchors_alias: str | None) -> str | None:
    """
    Why the top-level SELECT does not produce the columns the training join needs, or None.

    The join reads ``distinct_id`` and appends ``__label`` / ``__fold``, so the output must
    name ``distinct_id`` exactly once as the anchors table's own ``person_id`` field (an
    expression over it or a joined table's key is unique enough to pass the row check yet
    joins to no label), must not reuse the appended names, and must list every column: a
    wildcard hides both.
    """
    names: list[str] = []
    distinct_id_expr: ast.Expr | None = None
    for col in node.select or []:
        if isinstance(col, ast.Alias):
            names.append(col.alias)
            if col.alias == _DISTINCT_ID:
                distinct_id_expr = col.expr
        elif isinstance(col, ast.Field) and col.chain:
            name = str(col.chain[-1])
            if name == "*":
                return (
                    "feature_sql must list its output columns explicitly. A wildcard (*) can hide a second "
                    "distinct_id or a reserved column."
                )
            names.append(name)
    reserved = sorted(name for name in names if name in _RESERVED_OUTPUT_NAMES)
    if reserved:
        return (
            f"feature_sql must not output {', '.join(reserved)}: the training wrapper appends "
            "those columns to every feature row."
        )
    occurrences = names.count(_DISTINCT_ID)
    if occurrences > 1:
        return f"feature_sql outputs distinct_id {occurrences} times. Output it exactly once."
    expected = [anchors_alias, _PERSON_ID] if anchors_alias else [_PERSON_ID]
    if distinct_id_expr is None:
        return (
            f'feature_sql must select {".".join(expected)} AS distinct_id (e.g. "SELECT '
            f'{".".join(expected)} AS distinct_id, ..."). Materialization and the training join '
            "read that exact column, so each row keys one person."
        )
    if not isinstance(distinct_id_expr, ast.Field) or str(distinct_id_expr.chain[-1]) != _PERSON_ID:
        return (
            f"distinct_id must be the anchor person_id column itself ({'.'.join(expected)} AS distinct_id), "
            "not an expression over it. The training join compares it to the anchor key as is."
        )
    if [str(part) for part in distinct_id_expr.chain] != expected:
        return (
            f"distinct_id must be {'.'.join(expected)}, the person_id of the {{anchors}} table, not "
            "another relation's person_id. A joined table's key is null or missing for anchors it "
            "does not cover."
        )
    return None


def validate_unique_distinct_ids(
    rows: Iterable[Mapping[str, Any]], *, source: str = "feature_sql", expected_count: int | None = None
) -> None:
    """
    Enforce the one-row-per-person contract on materialized feature rows.

    Static SQL validation cannot prove row uniqueness — duplicate distinct_ids only become
    visible at materialization time, where they would flow into training as extra labeled
    examples for the duplicated persons. Pass ``expected_count`` (the number of anchors) to
    also require that every anchor produced exactly one row: an inner join or a WHERE on the
    joined table silently drops persons, and a target-correlated drop inflates the holdout.
    """
    seen: set[str] = set()
    duplicates: set[str] = set()
    missing = 0
    for row in rows:
        distinct_id = row.get("distinct_id")
        if distinct_id is None or not str(distinct_id).strip():
            # A row with no person cannot be joined to a label or a fold; materializing it
            # would serialize a synthetic empty identifier into the training data.
            missing += 1
            continue
        key = str(distinct_id)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        sample = ", ".join(sorted(duplicates)[:5])
        raise RecipeValidationError(
            f"{source} returned multiple rows for the same person ({len(duplicates)} duplicated "
            f"distinct_ids, e.g. {sample}). Each person must aggregate to exactly one row. "
            "Check the GROUP BY."
        )
    if missing:
        raise RecipeValidationError(
            f"{source} returned {missing} row(s) with a missing or blank person identifier. "
            "Every row must key exactly one person. Check the SELECT and the joins."
        )
    if expected_count is not None and len(seen) != expected_count:
        raise RecipeValidationError(
            f"{source} returned {len(seen)} person(s) but the anchors table has {expected_count}. "
            "Every anchor must produce exactly one row: drive the query FROM {anchors} with LEFT JOINs, "
            "and do not filter on the joined tables in WHERE."
        )


def validate_recipe(model_spec: object, recipe_snapshot: object) -> None:
    """
    Validate one recorded iteration. Both fields arrive as unconstrained JSON from the agent,
    so their shape is checked before anything is read. The ``model_class`` (in ``model_spec``)
    is required but not allowlisted — it is informational metadata; the agent's real model runs
    in a sandbox. The feature SQL (in ``recipe_snapshot``) is required and must pass
    ``validate_feature_sql``: the promotion and inference paths consume it as is.
    """
    if not isinstance(model_spec, Mapping):
        raise RecipeValidationError("model_spec must be a JSON object.")
    model_class = model_spec.get("model_class")
    if not isinstance(model_class, str) or not model_class.strip():
        raise RecipeValidationError("model_spec.model_class is required and must be a non-empty string.")
    if not isinstance(recipe_snapshot, Mapping):
        raise RecipeValidationError("recipe_snapshot must be a JSON object.")
    feature_sql = recipe_snapshot.get("feature_sql")
    if not isinstance(feature_sql, str) or not feature_sql.strip():
        raise RecipeValidationError("recipe_snapshot.feature_sql is required and must be a non-empty SELECT.")
    validate_feature_sql(feature_sql)
