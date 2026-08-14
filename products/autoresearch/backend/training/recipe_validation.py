"""Server-side validation of agent-authored model recipes.

Any agent — the in-house sandbox or an external bring-your-own agent — that records
a training iteration goes through ``validate_recipe``: the iteration's feature SQL must
be a read-only ``SELECT`` keyed on ``person_id`` (the one-row-per-person contract).

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
    if "person_id" not in _selected_names(node):
        raise RecipeValidationError(
            'feature_sql must select person_id (e.g. "SELECT person_id AS distinct_id, ...") '
            "so each row keys one person."
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


def _selected_names(node: ast.SelectQuery) -> set[str]:
    """Aliases and trailing field names of the SELECT columns."""
    names: set[str] = set()
    for col in node.select or []:
        inner = col
        if isinstance(col, ast.Alias):
            names.add(col.alias)
            inner = col.expr
        if isinstance(inner, ast.Field) and inner.chain:
            names.add(str(inner.chain[-1]))
    return names


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
    read-only ``SELECT`` keyed on ``person_id``.
    """
    if not (model_spec or {}).get("model_class"):
        raise RecipeValidationError("model_spec.model_class is required.")
    feature_sql = (recipe_snapshot or {}).get("feature_sql")
    if feature_sql:
        validate_feature_sql(feature_sql)
