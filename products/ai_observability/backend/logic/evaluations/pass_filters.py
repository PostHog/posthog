from uuid import UUID

from django.db.models import Q

from posthog.hogql.escape_sql import escape_hogql_string

from products.ai_observability.backend.models.evaluation_configs import (
    CategoricalOutputConfig,
    NumericOutputConfig,
    OutputType,
)
from products.ai_observability.backend.models.evaluations import Evaluation

from ...facade import contracts

# JSONExtract* reads the stored JSON value. `properties.$ai_evaluation_*` would go through HogQL property type
# inference, which can cast these keys to another type and silently drop events from the count.
_EVALUATION_ID = "JSONExtractString(properties, '$ai_evaluation_id')"
_RESULT = "JSONExtractRaw(properties, '$ai_evaluation_result')"
_SCORE = "JSONExtract(properties, '$ai_evaluation_numeric_result', 'Nullable(Float64)')"
_CATEGORIES = "JSONExtract(properties, '$ai_evaluation_categorical_result', 'Array(String)')"

# A skipped run can still store result=false, so it must leave the pass rate like an N/A run does.
_COUNTED = (
    "JSONExtractRaw(properties, '$ai_evaluation_skipped') != 'true' "
    "AND JSONExtractRaw(properties, '$ai_evaluation_applicable') != 'false'"
)
_BOOLEAN_GRADED = (
    f"JSONExtractString(properties, '$ai_evaluation_result_type') IN ('', 'boolean') AND {_RESULT} IN ('true', 'false')"
)
_BOOLEAN_PASSED = f"{_RESULT} = 'true'"


def build_evaluation_pass_filters(team_id: int) -> contracts.EvaluationPassFilters:
    graded_branches: list[str] = []
    passed_branches: list[str] = []
    for evaluation_id, output_type, output_config in _evaluations_with_own_rule(team_id):
        rule = _own_rule(output_type, output_config)
        if rule is None:
            continue
        graded, passed = rule
        matches_evaluation = f"{_EVALUATION_ID} = {escape_hogql_string(str(evaluation_id))}"
        graded_branches += [matches_evaluation, graded]
        passed_branches += [matches_evaluation, passed]

    graded = f"{_COUNTED} AND {_multi_if(graded_branches, _BOOLEAN_GRADED)}"
    return contracts.EvaluationPassFilters(
        graded=graded,
        passed=f"{graded} AND {_multi_if(passed_branches, _BOOLEAN_PASSED)}",
    )


def _evaluations_with_own_rule(team_id: int) -> list[tuple[UUID, str, dict]]:
    # Soft-deleted evaluations stay in, because their past events still need their own rule.
    return list(
        Evaluation.objects.filter(team_id=team_id)
        .filter(
            Q(output_type__in=[OutputType.NUMERIC, OutputType.CATEGORICAL]) | Q(output_config__true_is_failure=True)
        )
        .values_list("id", "output_type", "output_config")
    )


def _own_rule(output_type: str, output_config: dict) -> tuple[str, str] | None:
    """Return the (graded, passed) HogQL conditions for one evaluation, or None when the default rule applies
    or the evaluation has no pass rule at all."""
    try:
        if output_type == OutputType.NUMERIC:
            numeric_rule = NumericOutputConfig.model_validate(output_config).passing_rule
            if numeric_rule is None:
                return None
            operator = ">=" if numeric_rule.operator == "gte" else "<="
            return f"{_SCORE} IS NOT NULL", f"{_SCORE} {operator} {numeric_rule.threshold!r}"
        if output_type == OutputType.CATEGORICAL:
            categorical_rule = CategoricalOutputConfig.model_validate(output_config).passing_rule
            if categorical_rule is None:
                return None
            if not categorical_rule.categories:
                return "true", f"empty({_CATEGORIES})"
            passing = ", ".join(escape_hogql_string(category) for category in categorical_rule.categories)
            return "true", f"notEmpty({_CATEGORIES}) AND hasAll([{passing}], {_CATEGORIES})"
    except ValueError:
        return None
    if output_type == OutputType.BOOLEAN:
        return _BOOLEAN_GRADED, f"{_RESULT} = 'false'"
    return None


def _multi_if(branches: list[str], default: str) -> str:
    if not branches:
        return f"({default})"
    return f"multiIf({', '.join(branches)}, {default})"
