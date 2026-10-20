from django.db.models import Q

from posthog.hogql.escape_sql import escape_hogql_string

from products.ai_observability.backend.models.evaluation_configs import OutputType
from products.ai_observability.backend.models.evaluation_outcomes import (
    EvaluationReportOutcomeDefinition,
    get_outcome_definition,
)
from products.ai_observability.backend.models.evaluations import Evaluation

from ...facade import contracts

_DEFAULT_DEFINITION = get_outcome_definition(OutputType.BOOLEAN)


def build_evaluation_pass_filters(team_id: int) -> contracts.EvaluationPassFilters:
    graded_branches: list[str] = []
    passed_branches: list[str] = []
    # Every other evaluation falls through to the default rule. Soft-deleted evaluations stay in, because their past
    # events still need their own rule. Reads the writer, because a receiver of evaluation_output_changed calls this
    # right after the commit, before a replica can catch up.
    evaluations_with_own_rule = (
        Evaluation.objects.using("default")
        .filter(team_id=team_id)
        .filter(
            Q(output_type__in=[OutputType.NUMERIC, OutputType.CATEGORICAL, OutputType.SENTIMENT])
            | Q(output_config__true_is_failure=True)
        )
        .values_list("id", "output_type", "output_config")
    )
    for evaluation_id, output_type, output_config in evaluations_with_own_rule:
        try:
            definition = get_outcome_definition(
                output_type, true_is_failure=output_config.get("true_is_failure") is True, output_config=output_config
            )
        except ValueError:
            definition = None
        matches_evaluation = f"properties.$ai_evaluation_id = {escape_hogql_string(str(evaluation_id))}"
        # An evaluation without a pass rule grades none of its runs, including boolean runs from before it
        # switched to sentiment, which the default branch would otherwise grade.
        if definition is None or not definition.has_pass_rule:
            graded_branches += [matches_evaluation, "false"]
            passed_branches += [matches_evaluation, "false"]
            continue
        graded_branches += [matches_evaluation, _graded(definition)]
        passed_branches += [matches_evaluation, definition.outcome_predicates["pass"]]

    graded = _multi_if(graded_branches, _graded(_DEFAULT_DEFINITION))
    return contracts.EvaluationPassFilters(
        graded=graded,
        passed=f"({graded} AND {_multi_if(passed_branches, _DEFAULT_DEFINITION.outcome_predicates['pass'])})",
    )


def _graded(definition: EvaluationReportOutcomeDefinition) -> str:
    predicates = definition.outcome_predicates
    return f"{definition.event_predicate} AND (({predicates['pass']}) OR ({predicates['fail']}))"


def _multi_if(branches: list[str], default: str) -> str:
    if not branches:
        return f"({default})"
    return f"multiIf({', '.join(branches)}, {default})"
