"""Server-side validation of agent-authored model recipes.

Any agent — the in-house sandbox or an external bring-your-own agent — that records
a training iteration goes through this gate. The recipe's ``model_class`` is resolved
via ``importlib`` at inference time (a code-execution surface), so permitted classes
are an explicit allowlist; the feature SQL must be a read-only ``SELECT`` keyed on
``person_id`` (the one-row-per-person contract the inference compiler relies on).
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
    """Validate an iteration's model class (in ``model_spec``) and feature SQL (in ``recipe_snapshot``)."""
    model_class = (model_spec or {}).get("model_class")
    if not model_class:
        raise RecipeValidationError("model_spec.model_class is required.")
    validate_model_class(model_class)
    feature_sql = (recipe_snapshot or {}).get("feature_sql")
    if feature_sql:
        validate_feature_sql(feature_sql)
