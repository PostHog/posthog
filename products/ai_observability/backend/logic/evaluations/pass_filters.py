from uuid import UUID

from django.db.models import Q

from posthog.hogql.escape_sql import escape_hogql_string

from products.ai_observability.backend.models.evaluation_configs import OutputType
from products.ai_observability.backend.models.evaluations import Evaluation

from ...facade import contracts
from .outcomes import EvaluationReportOutcomeDefinition, get_outcome_definition

_DEFAULT_DEFINITION = get_outcome_definition(OutputType.BOOLEAN)


def build_evaluation_pass_filters(team_id: int) -> contracts.EvaluationPassFilters:
    graded_branches: list[str] = []
    passed_branches: list[str] = []
    for evaluation_id, output_type, output_config in _evaluations_with_own_rule(team_id):
        try:
            definition = get_outcome_definition(
                output_type, true_is_failure=output_config.get("true_is_failure") is True, output_config=output_config
            )
        except ValueError:
            continue
        if not definition.has_pass_rule:
            continue
        matches_evaluation = f"properties.$ai_evaluation_id = {escape_hogql_string(str(evaluation_id))}"
        graded_branches += [matches_evaluation, _graded(definition)]
        passed_branches += [matches_evaluation, definition.outcome_predicates["pass"]]

    graded = _multi_if(graded_branches, _graded(_DEFAULT_DEFINITION))
    return contracts.EvaluationPassFilters(
        graded=graded,
        passed=f"{graded} AND {_multi_if(passed_branches, _DEFAULT_DEFINITION.outcome_predicates['pass'])}",
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


def _graded(definition: EvaluationReportOutcomeDefinition) -> str:
    predicates = definition.outcome_predicates
    return f"{definition.event_predicate} AND (({predicates['pass']}) OR ({predicates['fail']}))"


def _multi_if(branches: list[str], default: str) -> str:
    if not branches:
        return f"({default})"
    return f"multiIf({', '.join(branches)}, {default})"
