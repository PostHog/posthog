import json
from collections.abc import Mapping
from datetime import datetime
from typing import Self

from posthog.dataclasses import frozen

from ...facade.contracts import EvaluationOutcome
from ...models.evaluation_configs import OutputType
from ...models.evaluation_outcomes import EvaluationReportOutcomeDefinition, get_outcome_definition
from .evaluation_result_queries import EvaluationResultRow
from .trace_queries import canonical_uuid, read_flag, read_number, read_text

_SENTIMENT_OUTCOMES: dict[str, EvaluationOutcome] = {"positive": "pass", "neutral": "unrated", "negative": "fail"}
UNKNOWN_EVALUATION_NAME = "Unknown evaluation"


def _outcome_definition(
    result_type: OutputType, output_config: Mapping[str, object]
) -> EvaluationReportOutcomeDefinition | None:
    # Stored configs are not revalidated on read, so a config that does not parse grades nothing.
    try:
        return get_outcome_definition(
            result_type, true_is_failure=output_config.get("true_is_failure") is True, output_config=dict(output_config)
        )
    except ValueError:
        return None


def _passes(
    definition: EvaluationReportOutcomeDefinition | None, result: object, applicable: bool | None
) -> bool | None:
    outcome = definition.label_for(result, applicable) if definition else None
    return outcome == "pass" if outcome in ("pass", "fail") else None


@frozen
class _Display:
    outcome: EvaluationOutcome
    label: str


_NOT_APPLICABLE = _Display(outcome="inconclusive", label="N/A")


def _graded(passed: bool | None, label: str) -> _Display:
    return _Display(outcome="unrated" if passed is None else "pass" if passed else "fail", label=label)


def _format_score(score: float) -> str:
    rounded = float(f"{score:.2f}") if abs(score) >= 1 else float(f"{score:.2g}")
    return str(int(rounded)) if rounded.is_integer() else repr(rounded)


def _result_type(raw: str | None) -> OutputType | None:
    return OutputType(raw) if raw in OutputType.values else None


def _parse_categories(raw: str | None, applicable: str | None) -> list[str] | None:
    if raw is None:
        return [] if read_flag(applicable) else None
    try:
        categories = json.loads(raw)
    except ValueError:
        return None
    if isinstance(categories, list) and all(isinstance(category, str) for category in categories):
        return categories
    return None


@frozen
class _RawResult:
    result_type: OutputType
    is_sentiment: bool
    sentiment_label: str | None
    result: bool | None
    applicable: bool | None
    skipped: bool
    score: float | None
    categories: list[str] | None

    @classmethod
    def from_row(cls, row: EvaluationResultRow) -> Self:
        sentiment_label = read_text(row.sentiment_label)
        result_type = _result_type(row.result_type) or (
            OutputType.SENTIMENT if row.evaluation_type == "sentiment" or sentiment_label else OutputType.BOOLEAN
        )
        not_applicable = row.applicable == "false"
        return cls(
            result_type=result_type,
            is_sentiment=result_type == OutputType.SENTIMENT
            or row.evaluation_type == "sentiment"
            or sentiment_label is not None,
            sentiment_label=sentiment_label,
            result=(
                None
                if result_type != OutputType.BOOLEAN or not_applicable or row.result is None
                else read_flag(row.result)
            ),
            applicable=None if row.applicable is None else read_flag(row.applicable),
            skipped=read_flag(row.skipped),
            score=read_number(row.score) if result_type == OutputType.NUMERIC and not not_applicable else None,
            categories=(
                _parse_categories(row.categories, row.applicable)
                if result_type == OutputType.CATEGORICAL and not not_applicable
                else None
            ),
        )

    def display(self, definition: EvaluationReportOutcomeDefinition | None) -> _Display:
        if self.skipped:
            return _Display(outcome="inconclusive", label="Skipped")
        if self.result_type == OutputType.CATEGORICAL:
            if self.applicable is False:
                return _NOT_APPLICABLE
            if self.categories is None:
                return _Display(outcome="inconclusive", label="No result")
            config = definition.categorical_config if definition else None
            names = {option.key: option.label for option in config.options} if config else {}
            label = ", ".join(names.get(key, key) for key in self.categories)
            return _graded(_passes(definition, self.categories, self.applicable), label or "No categories")
        if self.result_type == OutputType.NUMERIC:
            if self.applicable is False:
                return _NOT_APPLICABLE
            if self.score is None:
                return _Display(outcome="inconclusive", label="No score")
            passed = _passes(definition, self.score, self.applicable)
            label = _format_score(self.score)
            # A rounded label that would pass where the score fails, or the reverse, shows the score unrounded.
            rounded_passes = _passes(definition, float(label), self.applicable)
            return _graded(passed, label if rounded_passes == passed else str(self.score))
        if self.is_sentiment:
            sentiment = (self.sentiment_label or "unknown").lower()
            return _Display(
                outcome=_SENTIMENT_OUTCOMES.get(sentiment, "inconclusive"), label=sentiment[0].upper() + sentiment[1:]
            )
        if self.result is None:
            return _NOT_APPLICABLE
        return _graded(_passes(definition, self.result, self.applicable), "True" if self.result else "False")


@frozen
class EvaluationResult:
    id: str
    evaluation_id: str | None
    name: str
    target_node_id: str
    outcome: EvaluationOutcome
    label: str
    reasoning: str | None
    timestamp: datetime
    is_backfill: bool

    @classmethod
    def from_row(cls, row: EvaluationResultRow, *, trace_id: str, output_config: Mapping[str, object]) -> Self:
        raw = _RawResult.from_row(row)
        display = raw.display(_outcome_definition(raw.result_type, output_config))
        return cls(
            id=row.uuid,
            evaluation_id=row.evaluation_id if row.evaluation_id and canonical_uuid(row.evaluation_id) else None,
            name=read_text(row.evaluation_name) or UNKNOWN_EVALUATION_NAME,
            target_node_id=read_text(row.target_event_id) or trace_id,
            outcome=display.outcome,
            label=display.label,
            reasoning=read_text(row.reasoning),
            timestamp=row.timestamp,
            is_backfill=bool(read_text(row.backfill_id)),
        )
