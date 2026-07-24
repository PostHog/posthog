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

_OUTCOME_DEFINITIONS: Mapping[str, EvaluationReportOutcomeDefinition] = {
    "boolean": EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={
            "pass": "properties.$ai_evaluation_result = true AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)",
            "fail": "properties.$ai_evaluation_result = false AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)",
            "na": "properties.$ai_evaluation_applicable = false",
        },
        event_predicate=f"(properties.$ai_evaluation_result_type = 'boolean' OR isNull(properties.$ai_evaluation_result_type)) AND {_NOT_SKIPPED_PREDICATE}",
        result_expression="properties.$ai_evaluation_result",
        applicable_expression="properties.$ai_evaluation_applicable",
        score_expression="NULL",
    ),
    "sentiment": EvaluationReportOutcomeDefinition(
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
    ),
}

SUPPORTED_EVAL_REPORT_OUTPUT_TYPES = tuple(_OUTCOME_DEFINITIONS)


def get_outcome_definition(output_type: str | None) -> EvaluationReportOutcomeDefinition:
    normalized_output_type = output_type or "boolean"
    try:
        return _OUTCOME_DEFINITIONS[normalized_output_type]
    except KeyError as error:
        raise ValueError(f"Unsupported evaluation report output type: {normalized_output_type}") from error
