"""Trusted query definitions for evaluation report outcomes."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvaluationReportOutcomeDefinition:
    outcomes: tuple[str, ...]
    outcome_predicates: Mapping[str, str]
    event_predicate: str
    result_expression: str
    applicable_expression: str
    score_expression: str
    # Maps a raw result value (as read from the event) to its outcome label. Boolean detectors
    # flip this so a true result becomes a fail, not a pass. Empty for sentiment, whose label
    # is the result value itself.
    result_labels: Mapping[object, str] = field(default_factory=dict)


# String comparison is deliberate: an unregistered JSON bool property extracts as the
# string 'true', which the bool literal cannot compare against, while a registered
# Boolean property coerces correctly against the string form.
_NOT_SKIPPED_PREDICATE = "(isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')"

_BOOLEAN_APPLICABLE_CLAUSE = (
    "(isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != false)"
)

_BOOLEAN_EVENT_PREDICATE = (
    f"(properties.$ai_evaluation_result_type = 'boolean' OR isNull(properties.$ai_evaluation_result_type)) "
    f"AND {_NOT_SKIPPED_PREDICATE}"
)


def _boolean_definition(true_is_pass: bool) -> EvaluationReportOutcomeDefinition:
    """Build the boolean outcome definition for a given polarity.

    `true_is_pass=True` is the pass/fail default: a true result is a pass. Detector-style
    evaluations set it False so a true result (the flagged condition) is reported as a fail.
    """
    pass_bool = "true" if true_is_pass else "false"
    fail_bool = "false" if true_is_pass else "true"
    return EvaluationReportOutcomeDefinition(
        outcomes=("pass", "fail", "na"),
        outcome_predicates={
            "pass": f"properties.$ai_evaluation_result = {pass_bool} AND {_BOOLEAN_APPLICABLE_CLAUSE}",
            "fail": f"properties.$ai_evaluation_result = {fail_bool} AND {_BOOLEAN_APPLICABLE_CLAUSE}",
            "na": "properties.$ai_evaluation_applicable = false",
        },
        event_predicate=_BOOLEAN_EVENT_PREDICATE,
        result_expression="properties.$ai_evaluation_result",
        applicable_expression="properties.$ai_evaluation_applicable",
        score_expression="NULL",
        result_labels={True: "pass" if true_is_pass else "fail", False: "fail" if true_is_pass else "pass"},
    )


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

SUPPORTED_EVAL_REPORT_OUTPUT_TYPES = ("boolean", "sentiment")


def get_outcome_definition(output_type: str | None, *, true_is_pass: bool = True) -> EvaluationReportOutcomeDefinition:
    normalized_output_type = output_type or "boolean"
    if normalized_output_type == "boolean":
        return _boolean_definition(true_is_pass)
    if normalized_output_type == "sentiment":
        return _SENTIMENT_DEFINITION
    raise ValueError(f"Unsupported evaluation report output type: {normalized_output_type}")
