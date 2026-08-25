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
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

from products.autoresearch.backend.dataset.labeling import strip_sql_comments

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
_WALL_CLOCK_FUNCTIONS: frozenset[str] = frozenset({"now", "now64", "today", "yesterday"})


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
    if not _keys_person_id_as_distinct_id(node):
        raise RecipeValidationError(
            'feature_sql must select the anchor person_id aliased as distinct_id (e.g. "SELECT '
            'a.person_id AS distinct_id, ..."). Materialization and the training join read that '
            "exact column, so each row keys one person."
        )
    wall_clock = _WALL_CLOCK_FUNCTIONS & _call_names(node)
    if wall_clock:
        raise RecipeValidationError(
            f"feature_sql must not call {', '.join(sorted(wall_clock))}(). Bound every time "
            "window to fromUnixTimestamp(a.cutoff_ts) so features stop at each user's T0."
        )
    # The framework substitutes {anchors} with the per-user (person_id, cutoff_ts) table via a
    # plain string replace, which is a silent no-op when the placeholder is absent — the SQL
    # would then run with no per-user T0 cutoff and read the outcome window (target leakage).
    # Substitution strips comments first, so a placeholder that only appears inside a comment
    # does not count: check the same text the substitution will see.
    if "{anchors}" not in strip_sql_comments(feature_sql):
        raise RecipeValidationError(
            "feature_sql must read FROM the {anchors} placeholder table (columns person_id, "
            "cutoff_ts) so features are cut off at each user's T0 and cannot leak the outcome window."
        )


class _CallNames(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_call(self, node: ast.Call) -> None:
        self.names.add(node.name)
        super().visit_call(node)


class _FieldTails(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.tails: set[str] = set()

    def visit_field(self, node: ast.Field) -> None:
        if node.chain:
            self.tails.add(str(node.chain[-1]))
        super().visit_field(node)


def _call_names(node: ast.SelectQuery) -> set[str]:
    """Every function name called anywhere in the query, subqueries included."""
    visitor = _CallNames()
    visitor.visit(node)
    return visitor.names


def _keys_person_id_as_distinct_id(node: ast.SelectQuery) -> bool:
    """True when some SELECT column is ``<expression over person_id> AS distinct_id``."""
    for col in node.select or []:
        if not isinstance(col, ast.Alias) or col.alias != "distinct_id":
            continue
        fields = _FieldTails()
        fields.visit(col.expr)
        if "person_id" in fields.tails:
            return True
    return False


def validate_unique_distinct_ids(rows: Iterable[Mapping[str, Any]], *, source: str = "feature_sql") -> None:
    """
    Enforce the one-row-per-person contract on materialized feature rows.

    Static SQL validation cannot prove row uniqueness — duplicate distinct_ids only become
    visible at materialization time, where they would flow into training as extra labeled
    examples for the duplicated persons.
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
            f"distinct_ids, e.g. {sample}). Each person must aggregate to exactly one row — "
            "check the GROUP BY."
        )
    if missing:
        raise RecipeValidationError(
            f"{source} returned {missing} row(s) with a missing or blank person identifier. "
            "Every row must key exactly one person — check the SELECT and the joins."
        )


def validate_recipe(model_spec: dict, recipe_snapshot: dict) -> None:
    """
    Validate one recorded iteration. The ``model_class`` (in ``model_spec``) is required
    but not allowlisted — it is informational metadata; the agent's real model runs in a
    sandbox. Only the feature SQL (in ``recipe_snapshot``) is sanity-checked: it must be a
    read-only ``SELECT`` keyed as ``person_id AS distinct_id``.
    """
    if not (model_spec or {}).get("model_class"):
        raise RecipeValidationError("model_spec.model_class is required.")
    feature_sql = (recipe_snapshot or {}).get("feature_sql")
    if feature_sql:
        validate_feature_sql(feature_sql)
