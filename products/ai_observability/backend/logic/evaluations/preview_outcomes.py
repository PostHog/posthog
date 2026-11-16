from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from posthog.dataclasses import frozen

from ...facade import contracts
from ...models.evaluation_outcomes import EvaluationReportOutcomeDefinition, get_outcome_definition

_OUTCOMES: tuple[contracts.PreviewOutcome, ...] = ("pass", "fail", "na", "error")


@frozen
class PreviewGrader:
    """Grades a preview row the way reports grade a saved run, so both agree on polarity and thresholds."""

    output_type: str
    definition: EvaluationReportOutcomeDefinition

    def outcome(
        self, *, error: str | None, result: bool | None, score: float | None, categories: Sequence[str] | None
    ) -> contracts.PreviewOutcome | None:
        """None for a result the evaluation has no rule to grade, such as a score with no passing rule."""
        if error:
            return "error"
        value: object = (
            categories if self.output_type == "categorical" else score if self.output_type == "numeric" else result
        )
        label = self.definition.label_for(value, applicable=value is not None)
        return cast(contracts.PreviewOutcome, label) if label in _OUTCOMES else None


def preview_grader(output_type: str, output_config: Mapping[str, Any] | None) -> PreviewGrader:
    config = dict(output_config or {})
    return PreviewGrader(
        output_type=output_type,
        definition=get_outcome_definition(
            output_type, true_is_failure=config.get("true_is_failure") is True, output_config=config
        ),
    )


def outcome_counts(outcomes: Iterable[contracts.PreviewOutcome | None]) -> dict[str, int]:
    counts = Counter(outcomes)
    return {f"{outcome}_count": counts[outcome] for outcome in _OUTCOMES}
