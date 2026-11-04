import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from posthog.dataclasses import frozen

from ...models.score_definitions import ScoreDefinition

REVIEWED_WITHOUT_SELECTION = "Reviewed"
DEFAULT_TRUE_LABEL = "Yes"
DEFAULT_FALSE_LABEL = "No"

_TRAILING_DECIMAL_ZEROS = re.compile(r"(\.\d*?)0+$")
_TRAILING_DECIMAL_POINT = re.compile(r"\.$")


@frozen
class ReviewScore:
    name: str
    value: str

    @property
    def label(self) -> str:
        return f"{self.name}: {self.value}"


@frozen
class HumanReview:
    reviewed_by: str | None
    reviewed_at: datetime
    comment: str | None
    scores: tuple[ReviewScore, ...]


@frozen
class QueueAssignment:
    queue_id: str
    queue_name: str
    item_id: str


@frozen
class TraceReviewState:
    review: HumanReview | None
    queue: QueueAssignment | None


def score_display_value(
    kind: str,
    config: Mapping[str, object] | None,
    categorical_values: Sequence[str] | None,
    numeric_value: Decimal | None,
    boolean_value: bool | None,
) -> str:
    """A saved score as a reviewer reads it, using the scorer config snapshot the score was saved with."""
    if kind == ScoreDefinition.Kind.CATEGORICAL:
        return _categorical_value(config, categorical_values or [])
    if kind == ScoreDefinition.Kind.NUMERIC:
        return _numeric_value(numeric_value)
    return _boolean_value(config, boolean_value)


def reviewer_name(first_name: str, email: str, distinct_id: str | None) -> str | None:
    return first_name or email or distinct_id or None


def _categorical_value(config: Mapping[str, object] | None, selected: Sequence[str]) -> str:
    if not selected:
        return REVIEWED_WITHOUT_SELECTION
    labels = _option_labels(config)
    return ", ".join(labels.get(key) or key for key in selected)


def _option_labels(config: Mapping[str, object] | None) -> dict[str, str]:
    options = config.get("options") if config else None
    if not isinstance(options, list):
        return {}
    return {
        option["key"]: option["label"]
        for option in options
        if isinstance(option, dict) and isinstance(option.get("key"), str) and isinstance(option.get("label"), str)
    }


def _numeric_value(value: Decimal | None) -> str:
    if value is None:
        return ""
    return _TRAILING_DECIMAL_POINT.sub("", _TRAILING_DECIMAL_ZEROS.sub(r"\1", str(value)))


def _boolean_value(config: Mapping[str, object] | None, value: bool | None) -> str:
    label = config.get("true_label" if value is True else "false_label") if config else None
    if isinstance(label, str) and label:
        return label
    return DEFAULT_TRUE_LABEL if value is True else DEFAULT_FALSE_LABEL
