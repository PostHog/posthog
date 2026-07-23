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

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

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
