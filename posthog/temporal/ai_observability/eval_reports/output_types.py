"""Trusted query definitions for evaluation report outcomes."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationReportOutcomeDefinition:
    outcomes: tuple[str, ...]
    outcome_predicates: Mapping[str, str]
    event_predicate: str
    result_expression: str
    applicable_expression: str
    score_expression: str


# String comparison is deliberate: an unregistered JSON bool property extracts as the
# string 'true', which the bool literal cannot compare against, while a registered
# Boolean property coerces correctly against the string form.
_NOT_SKIPPED_PREDICATE = "(isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')"

_APPLICABLE_PREDICATE = (
    "(isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)"
)

# A boolean judge prompt can be framed either way: "true means it succeeded" (the
# default) or "true means the thing was detected" (a detector-style prompt, e.g. "return
# true when the agent struggled"). For a detector prompt, `$ai_evaluation_result = true`
# is the bad outcome, so it must count toward "fail" — not "pass" — or every report
# reads exactly backwards relative to what the judge's own prompt means.
TRUE_IS_PASS = "true_is_pass"
TRUE_IS_FAIL = "true_is_fail"
DEFAULT_BOOLEAN_POLARITY = TRUE_IS_PASS
BOOLEAN_POLARITIES: tuple[str, ...] = (TRUE_IS_PASS, TRUE_IS_FAIL)

_SENTIMENT_DEFINITION = EvaluationReportOutcomeDefinition(
    outcomes=("positive", "neutral", "negative"),
    outcome_predicates={
        "positive": "properties.$ai_sentiment_label = 'positive'",
        "neutral": "properties.$ai_sentiment_label = 'neutral'",
        "negative": "properties.$ai_sentiment_label = 'negative'",
    },
    event_predicate=f"properties.$ai_evaluation_result_type = 'sentiment' AND {_NOT_SKIPPED_PREDICATE}",
    result_expression="properties.$ai_sentiment_label",
    applicable_expression="NULL",
    score_expression="properties.$ai_sentiment_score",
)


def _boolean_definition(polarity: str) -> EvaluationReportOutcomeDefinition:
    pass_value, fail_value = ("true", "false") if polarity == TRUE_IS_PASS else ("false", "true")
    return EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={
            "pass": f"properties.$ai_evaluation_result = {pass_value} AND {_APPLICABLE_PREDICATE}",
            "fail": f"properties.$ai_evaluation_result = {fail_value} AND {_APPLICABLE_PREDICATE}",
            "na": "properties.$ai_evaluation_applicable = false",
        },
        event_predicate=f"(properties.$ai_evaluation_result_type = 'boolean' OR isNull(properties.$ai_evaluation_result_type)) AND {_NOT_SKIPPED_PREDICATE}",
        result_expression="properties.$ai_evaluation_result",
        applicable_expression="properties.$ai_evaluation_applicable",
        score_expression="NULL",
    )


_OUTCOME_DEFINITIONS: Mapping[str, EvaluationReportOutcomeDefinition] = {
    "boolean": _boolean_definition(DEFAULT_BOOLEAN_POLARITY),
    "sentiment": _SENTIMENT_DEFINITION,
}

SUPPORTED_EVAL_REPORT_OUTPUT_TYPES = tuple(_OUTCOME_DEFINITIONS)


def get_outcome_definition(output_type: str | None, polarity: str | None = None) -> EvaluationReportOutcomeDefinition:
    normalized_output_type = output_type or "boolean"
    if normalized_output_type == "boolean":
        return _boolean_definition(polarity or DEFAULT_BOOLEAN_POLARITY)
    try:
        return _OUTCOME_DEFINITIONS[normalized_output_type]
    except KeyError as error:
        raise ValueError(f"Unsupported evaluation report output type: {normalized_output_type}") from error
