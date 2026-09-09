"""Trusted query definitions for evaluation report outcomes.

Only `outcome_predicates` and `label_for` depend on the evaluation's polarity. `event_predicate`,
`outcomes`, `result_expression`, `applicable_expression` and `score_expression` do not, so a caller
that reads only those is correct without passing `true_is_failure`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

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

    def label_for(self, result: object, applicable: object = None) -> str | None:
        """Map one raw result value to its outcome label, or None when it is not one we report."""
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
_NOT_SKIPPED_PREDICATE = "(isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')"

_APPLICABLE_PREDICATE = (
    "(isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)"
)


def _boolean_definition(true_is_failure: bool) -> EvaluationReportOutcomeDefinition:
    passing_result = not true_is_failure
    pass_literal = "true" if passing_result else "false"
    fail_literal = "false" if passing_result else "true"
    return EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={
            "pass": f"properties.$ai_evaluation_result = {pass_literal} AND {_APPLICABLE_PREDICATE}",
            "fail": f"properties.$ai_evaluation_result = {fail_literal} AND {_APPLICABLE_PREDICATE}",
            "na": "properties.$ai_evaluation_applicable = false",
        },
        event_predicate=(
            "(properties.$ai_evaluation_result_type = 'boolean' OR isNull(properties.$ai_evaluation_result_type)) "
            f"AND {_NOT_SKIPPED_PREDICATE}"
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
        event_predicate=f"properties.$ai_evaluation_result_type = 'sentiment' AND {_NOT_SKIPPED_PREDICATE}",
        result_expression="properties.$ai_sentiment_label",
        applicable_expression="NULL",
        score_expression="properties.$ai_sentiment_score",
        passing_result=None,
    )


_DEFINITION_BUILDERS: Mapping[str, Callable[[bool], EvaluationReportOutcomeDefinition]] = {
    "boolean": _boolean_definition,
    "sentiment": _sentiment_definition,
}

SUPPORTED_EVAL_REPORT_OUTPUT_TYPES = tuple(_DEFINITION_BUILDERS)


def get_outcome_definition(
    output_type: str | None, *, true_is_failure: bool = False
) -> EvaluationReportOutcomeDefinition:
    normalized_output_type = output_type or "boolean"
    try:
        builder = _DEFINITION_BUILDERS[normalized_output_type]
    except KeyError as error:
        raise ValueError(f"Unsupported evaluation report output type: {normalized_output_type}") from error
    return builder(true_is_failure)
