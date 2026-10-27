from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Literal

from django.db.models import Q

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_string
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen

from products.ai_observability.backend.models.evaluation_configs import OutputType
from products.ai_observability.backend.models.evaluation_outcomes import (
    EvaluationReportOutcomeDefinition,
    RulePredicates,
    categorical_rule_predicates,
    get_outcome_definition,
    numeric_rule_predicates,
)
from products.ai_observability.backend.models.evaluations import Evaluation

from ...facade import contracts

_DEFAULT_DEFINITION = get_outcome_definition(OutputType.BOOLEAN)
_EVALUATION_ID = "properties.$ai_evaluation_id"


@frozen
class PassRules:
    """The pass filters as parsed HogQL, with each evaluation's rule looked up from array placeholders."""

    graded: ast.Expr
    # Only means pass on a graded run, so a passed run is `graded AND passes`.
    passes: ast.Expr


def build_evaluation_pass_filters(team_id: int) -> contracts.EvaluationPassFilters:
    graded_branches: list[str] = []
    passed_branches: list[str] = []
    for evaluation_id, definition in _own_rules(team_id, None):
        matches_evaluation = f"{_EVALUATION_ID} = {escape_hogql_string(evaluation_id)}"
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


def build_pass_rules(team_id: int, evaluation_ids: Sequence[str]) -> PassRules:
    """The same rules as `build_evaluation_pass_filters`, in one branch per kind of rule rather than per evaluation,
    so the query stays the same size however many evaluations it reads."""
    no_rule: list[str] = []
    inverted: list[str] = []
    no_category: list[str] = []
    numeric: dict[Literal["gte", "lte"], list[tuple[str, float]]] = defaultdict(list)
    categorical: list[tuple[str, list[str]]] = []
    for evaluation_id, definition in _own_rules(team_id, evaluation_ids):
        if definition is None or not definition.has_pass_rule:
            no_rule.append(evaluation_id)
        elif definition.numeric_config is not None and definition.numeric_config.passing_rule is not None:
            rule = definition.numeric_config.passing_rule
            numeric[rule.operator].append((evaluation_id, rule.threshold))
        elif definition.categorical_config is not None and definition.categorical_config.passing_rule is not None:
            categories = definition.categorical_config.passing_rule.categories
            if categories:
                categorical.append((evaluation_id, categories))
            else:
                no_category.append(evaluation_id)
        elif definition.passing_result is False:
            inverted.append(evaluation_id)

    placeholders: dict[str, ast.Expr] = {}
    graded_branches: list[str] = []
    passed_branches: list[str] = []

    # A kind without evaluations gets no branch, because HogQL cannot type an empty array constant.
    def branch(name: str, ids: Sequence[str], graded: str, passed: str) -> None:
        placeholders[f"{name}_ids"] = ast.Constant(value=list(ids))
        matches = f"{_EVALUATION_ID} IN {{{name}_ids}}"
        graded_branches.extend([matches, graded])
        passed_branches.extend([matches, passed])

    def rule_branch(name: str, ids: Sequence[str], event_predicate: str, predicates: RulePredicates) -> None:
        branch(name, ids, _graded_from(event_predicate, predicates.passed, predicates.failed), predicates.passed)

    if no_rule:
        branch("no_rule", no_rule, "false", "false")
    if inverted:
        definition = get_outcome_definition(OutputType.BOOLEAN, true_is_failure=True)
        outcome = definition.outcome_predicates
        rule_branch(
            "inverted",
            inverted,
            definition.event_predicate,
            RulePredicates(passed=outcome["pass"], failed=outcome["fail"]),
        )
    numeric_event = get_outcome_definition(OutputType.NUMERIC).event_predicate
    for operator, rules in numeric.items():
        name = f"numeric_{operator}"
        placeholders[f"{name}_thresholds"] = ast.Constant(value=[threshold for _, threshold in rules])
        # `transform` looks up a constant array through a hash table, where `indexOf` scans it on every run.
        threshold = f"transform({_EVALUATION_ID}, {{{name}_ids}}, {{{name}_thresholds}}, 0)"
        ids = [evaluation_id for evaluation_id, _ in rules]
        rule_branch(name, ids, numeric_event, numeric_rule_predicates(operator, threshold))
    categorical_event = get_outcome_definition(OutputType.CATEGORICAL).event_predicate
    if no_category:
        rule_branch("no_category", no_category, categorical_event, categorical_rule_predicates(None))
    if categorical:
        placeholders["categorical_passing"] = ast.Constant(value=[categories for _, categories in categorical])
        placeholders["categorical_positions"] = ast.Constant(value=list(range(1, len(categorical) + 1)))
        # `transform` cannot return an array, so it returns the position of the evaluation's categories instead.
        position = f"transform({_EVALUATION_ID}, {{categorical_ids}}, {{categorical_positions}}, 0)"
        passing = f"arrayElement({{categorical_passing}}, {position})"
        ids = [evaluation_id for evaluation_id, _ in categorical]
        rule_branch("categorical", ids, categorical_event, categorical_rule_predicates(passing))

    graded = _multi_if(graded_branches, _graded(_DEFAULT_DEFINITION))
    passes = _multi_if(passed_branches, _DEFAULT_DEFINITION.outcome_predicates["pass"])
    return PassRules(
        graded=parse_expr(graded, placeholders=placeholders), passes=parse_expr(passes, placeholders=placeholders)
    )


def _own_rules(
    team_id: int, evaluation_ids: Sequence[str] | None
) -> Iterator[tuple[str, EvaluationReportOutcomeDefinition | None]]:
    """Each evaluation whose runs the default rule does not grade, with its rule, or None for a config that no longer
    loads. Soft-deleted evaluations stay in, because their past events still need their own rule."""
    evaluations = Evaluation.objects.filter(team_id=team_id)
    if evaluation_ids is not None:
        evaluations = evaluations.filter(id__in=evaluation_ids)
    evaluations_with_own_rule = evaluations.filter(
        Q(output_type__in=[OutputType.NUMERIC, OutputType.CATEGORICAL, OutputType.SENTIMENT])
        | Q(output_config__true_is_failure=True)
    ).values_list("id", "output_type", "output_config")
    for evaluation_id, output_type, output_config in evaluations_with_own_rule:
        try:
            definition = get_outcome_definition(
                output_type, true_is_failure=output_config.get("true_is_failure") is True, output_config=output_config
            )
        except ValueError:
            definition = None
        yield str(evaluation_id), definition


def _graded(definition: EvaluationReportOutcomeDefinition) -> str:
    predicates = definition.outcome_predicates
    return _graded_from(definition.event_predicate, predicates["pass"], predicates["fail"])


def _graded_from(event_predicate: str, passed: str, failed: str) -> str:
    return f"{event_predicate} AND (({passed}) OR ({failed}))"


def _multi_if(branches: list[str], default: str) -> str:
    if not branches:
        return f"({default})"
    return f"multiIf({', '.join(branches)}, {default})"
