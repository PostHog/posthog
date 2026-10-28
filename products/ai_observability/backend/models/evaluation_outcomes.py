"""Trusted query definitions for evaluation outcomes, shared by reports and the pass filters other products use.

Only `outcome_predicates` and `label_for` depend on the evaluation's passing rule. `event_predicate`,
`outcomes`, `result_expression`, `applicable_expression` and `score_expression` do not, so a caller
that reads only those is correct without passing `true_is_failure` or `output_config`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.dataclasses import frozen

from products.ai_observability.backend.models.evaluation_configs import CategoricalOutputConfig, NumericOutputConfig

SENTIMENT_LABELS = ("positive", "neutral", "negative")


@dataclass(frozen=True)
class EvaluationReportOutcomeDefinition:
    outcomes: tuple[str, ...]
    outcome_predicates: Mapping[str, str]
    event_predicate: str
    result_expression: str
    applicable_expression: str
    score_expression: str
    # Which raw boolean is the desirable outcome, or None for an output type that labels itself.
    passing_result: bool | None
    numeric_config: NumericOutputConfig | None = None
    categorical_config: CategoricalOutputConfig | None = None

    @property
    def has_pass_rule(self) -> bool:
        if self.numeric_config is not None:
            return self.numeric_config.passing_rule is not None
        if self.categorical_config is not None:
            return self.categorical_config.passing_rule is not None
        return self.passing_result is not None

    def label_for(self, result: object, applicable: object = None) -> str | None:
        """Map one raw result value to its outcome label, or None when it is not one we report."""
        if self.categorical_config is not None:
            if applicable in (False, "false"):
                return "na"
            rule = self.categorical_config.passing_rule
            if rule is None or not isinstance(result, list) or not all(isinstance(value, str) for value in result):
                return None
            return "pass" if rule.passes(result) else "fail"
        if self.numeric_config is not None:
            if applicable in (False, "false"):
                return "na"
            if self.numeric_config.passing_rule is None:
                return None
            try:
                score = NumericOutputConfig().validate_score(result)
            except ValueError:
                return None
            return "pass" if self.numeric_config.passing_rule.passes(score) else "fail"
        if self.passing_result is None:
            return result if isinstance(result, str) and result in self.outcomes else None
        if applicable is False:
            return "na"
        # Accepts 1/0 alongside True/False: a ClickHouse UInt8 column can hand back an int
        # for what is logically a boolean result.
        if result not in (True, False):
            return None
        return "pass" if bool(result) is self.passing_result else "fail"


# String comparison is deliberate: an unregistered JSON bool property extracts as the
# string 'true', which the bool literal cannot compare against, while a registered
# Boolean property coerces correctly against the string form.
NOT_SKIPPED_PREDICATE = "(isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')"

APPLICABLE_PREDICATE = (
    "(isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != 'false')"
)


def _boolean_definition(true_is_failure: bool) -> EvaluationReportOutcomeDefinition:
    passing_result = not true_is_failure
    pass_literal = "'true'" if passing_result else "'false'"
    fail_literal = "'false'" if passing_result else "'true'"
    return EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={
            "pass": f"properties.$ai_evaluation_result = {pass_literal} AND {APPLICABLE_PREDICATE}",
            "fail": f"properties.$ai_evaluation_result = {fail_literal} AND {APPLICABLE_PREDICATE}",
            "na": "properties.$ai_evaluation_applicable = 'false'",
        },
        event_predicate=(
            "(properties.$ai_evaluation_result_type = 'boolean' OR isNull(properties.$ai_evaluation_result_type)) "
            f"AND {NOT_SKIPPED_PREDICATE}"
        ),
        result_expression="properties.$ai_evaluation_result",
        applicable_expression="properties.$ai_evaluation_applicable",
        score_expression="NULL",
        passing_result=passing_result,
    )


def _sentiment_definition(true_is_failure: bool) -> EvaluationReportOutcomeDefinition:
    return EvaluationReportOutcomeDefinition(
        outcomes=SENTIMENT_LABELS,
        outcome_predicates={label: f"properties.$ai_sentiment_label = '{label}'" for label in SENTIMENT_LABELS},
        event_predicate=f"properties.$ai_evaluation_result_type = 'sentiment' AND {NOT_SKIPPED_PREDICATE}",
        result_expression="properties.$ai_sentiment_label",
        applicable_expression="NULL",
        score_expression="properties.$ai_sentiment_score",
        passing_result=None,
    )


_DEFINITION_BUILDERS: Mapping[str, Callable[[bool], EvaluationReportOutcomeDefinition]] = {
    "boolean": _boolean_definition,
    "sentiment": _sentiment_definition,
}

SUPPORTED_EVAL_REPORT_OUTPUT_TYPES = (*_DEFINITION_BUILDERS, "numeric", "categorical")


CATEGORIES_EXPRESSION = "JSONExtract(ifNull(properties.$ai_evaluation_categorical_result, '[]'), 'Array(String)')"
SCORE_EXPRESSION = "toFloat(properties.$ai_evaluation_numeric_result)"
_NUMERIC_EVENT_PREDICATE = f"properties.$ai_evaluation_result_type = 'numeric' AND {NOT_SKIPPED_PREDICATE}"
_CATEGORICAL_EVENT_PREDICATE = f"properties.$ai_evaluation_result_type = 'categorical' AND {NOT_SKIPPED_PREDICATE}"
# A categorical run is graded only when the judge said it applies, where a numeric run is graded unless it said not.
_CATEGORICAL_APPLICABLE_PREDICATE = "properties.$ai_evaluation_applicable = 'true'"
# A run that produced a score or chose its categories, with or without a passing rule. Same as
# EVALUATION_NUMERIC_GRADED_HOGQL and EVALUATION_CATEGORICAL_GRADED_HOGQL in the frontend's constants.ts.
NUMERIC_SCORED_PREDICATE = (
    f"{_NUMERIC_EVENT_PREDICATE} AND properties.$ai_evaluation_numeric_result IS NOT NULL AND {APPLICABLE_PREDICATE}"
)
CATEGORIZED_PREDICATE = f"{_CATEGORICAL_EVENT_PREDICATE} AND {_CATEGORICAL_APPLICABLE_PREDICATE}"


@frozen
class RulePredicates:
    passed: str
    failed: str


def categorical_rule_predicates(passing_categories: str | None) -> RulePredicates:
    """The pass and fail predicates of a categorical passing rule. `passing_categories` is a HogQL array, or None
    for a rule that passes only a run that chose no category."""
    if passing_categories is None:
        passing = f"empty({CATEGORIES_EXPRESSION})"
    else:
        passing = f"(notEmpty({CATEGORIES_EXPRESSION}) AND hasAll({passing_categories}, {CATEGORIES_EXPRESSION}))"
    return RulePredicates(
        passed=f"{passing} AND {_CATEGORICAL_APPLICABLE_PREDICATE}",
        failed=f"NOT {passing} AND {_CATEGORICAL_APPLICABLE_PREDICATE}",
    )


def numeric_rule_predicates(operator: Literal["gte", "lte"], threshold: str) -> RulePredicates:
    """The pass and fail predicates of a numeric passing rule. `threshold` is a HogQL expression."""
    passed_op, failed_op = (">=", "<") if operator == "gte" else ("<=", ">")
    return RulePredicates(
        passed=f"{SCORE_EXPRESSION} {passed_op} {threshold} AND {APPLICABLE_PREDICATE}",
        failed=f"{SCORE_EXPRESSION} {failed_op} {threshold} AND {APPLICABLE_PREDICATE}",
    )


def _categorical_definition(output_config: dict | None) -> EvaluationReportOutcomeDefinition:
    config = CategoricalOutputConfig.model_validate(output_config) if output_config else None
    passed_predicate = "false"
    failed_predicate = "false"

    if config is not None and config.passing_rule is not None:
        categories = config.passing_rule.categories
        predicates = categorical_rule_predicates(
            f"[{', '.join(escape_hogql_string(category) for category in categories)}]" if categories else None
        )
        passed_predicate, failed_predicate = predicates.passed, predicates.failed

    return EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={
            "pass": passed_predicate,
            "fail": failed_predicate,
            "na": "properties.$ai_evaluation_applicable = 'false'",
        },
        event_predicate=_CATEGORICAL_EVENT_PREDICATE,
        result_expression=CATEGORIES_EXPRESSION,
        applicable_expression="properties.$ai_evaluation_applicable",
        score_expression="NULL",
        passing_result=None,
        categorical_config=config,
    )


def _numeric_definition(output_config: dict | None) -> EvaluationReportOutcomeDefinition:
    config = NumericOutputConfig.model_validate(output_config or {})
    passed = failed = "false"
    if config.passing_rule is not None:
        predicates = numeric_rule_predicates(config.passing_rule.operator, repr(config.passing_rule.threshold))
        passed, failed = predicates.passed, predicates.failed
    return EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={"pass": passed, "fail": failed, "na": "properties.$ai_evaluation_applicable = 'false'"},
        event_predicate=_NUMERIC_EVENT_PREDICATE,
        result_expression=SCORE_EXPRESSION,
        applicable_expression="properties.$ai_evaluation_applicable",
        score_expression=SCORE_EXPRESSION,
        passing_result=None,
        numeric_config=config,
    )


def get_outcome_definition(
    output_type: str | None, *, true_is_failure: bool = False, output_config: dict | None = None
) -> EvaluationReportOutcomeDefinition:
    normalized_output_type = output_type or "boolean"
    if normalized_output_type == "categorical":
        return _categorical_definition(output_config)
    if normalized_output_type == "numeric":
        return _numeric_definition(output_config)
    try:
        builder = _DEFINITION_BUILDERS[normalized_output_type]
    except KeyError as error:
        raise ValueError(f"Unsupported evaluation report output type: {normalized_output_type}") from error
    return builder(true_is_failure)
