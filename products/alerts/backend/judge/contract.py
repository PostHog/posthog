"""The seam between alert evaluation and a judge that reasons about a series.

A statistical detector in ``posthog.tasks.alerts.detectors`` scores a bare array of values
and nothing else. A judge reads what the series means and who is asking: the calendar, the
metric definition, the author's notes, and the team and person its charged model call is
attributed to. That is a different contract, so it lives here in the product instead of on
``BaseDetector``, and the shared detector registry stays value-only.

This module stays light on purpose: the facade re-exports from it, so it must not pull the
model client, the prompt, or the evaluation package onto every facade consumer's import path.
"""

from typing import TYPE_CHECKING, Any, Literal, Protocol

import numpy as np

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

AnomalyKind = Literal["spike", "drop", "flatline", "trend_break", "level_shift", "pattern_change", "none"]

# Bounds what one check can send, whatever lookback the interval asks for.
MAX_PROMPT_POINTS = 400

# Bound on model calls in flight per process. The evaluate activity runs AI checks on a
# dedicated executor of this size, so a check there never waits on the judge's own slot.
MAX_CONCURRENT_MODEL_CALLS = 8


class LLMDetectorError(Exception):
    """The judge could not reach a verdict for this check.

    Never swallowed into "no anomaly": an alert that silently stops firing because a
    model call failed is worse than one that reports an error, so this propagates and
    the check is recorded as errored (after Temporal retries).
    """


class LLMDetectorUnavailableError(LLMDetectorError):
    """A transport failure, timeout, or unusable model output. Worth retrying."""


class LLMDetectorMisconfiguredError(LLMDetectorError):
    """The judge cannot run as configured, so retrying cannot help.

    The creator is missing, AI data processing consent is withdrawn, or the rollout is disabled.
    """


# What the alert's owner reads on a check the judge could not reach a verdict for. The raw
# transport error can carry an internal detail, so the check history and the error email show
# this instead, and the code is what lets it past the serializer's allowlist. The wording names
# the outcome and not a cause: the same error also covers a rollout lookup that returned nothing,
# a worker with no free model-call slot, and a model reply the judge could not read.
LLM_DETECTOR_UNAVAILABLE_ERROR_CODE = "llm_detector_unavailable"
LLM_DETECTOR_UNAVAILABLE_MESSAGE = (
    "The AI detector could not complete this check. The alert is still on and the next check tries again."
)


@frozen
class EarlierFlag:
    """A point that an earlier check of the same alert fired on, with the reason it gave."""

    date: str
    # Model output from that check. Untrusted, because it can echo series labels.
    rationale: str


@frozen
class SeriesContext:
    """What the series means: everything the judge reads that the values array cannot carry."""

    # Aligned index-for-index with the values array; None for a non-time-series point.
    dates: tuple[str | None, ...] = ()
    interval: str | None = None
    series_label: str = ""
    # From describe_metric_definition; "" when the caller could not read the query.
    metric_description: str = ""
    insight_name: str = ""
    # The alert author's free text describing what counts as unusual. Untrusted input.
    instructions: str = ""
    # Points that earlier AI checks of this alert fired on. Empty for a new alert.
    earlier_flags: tuple[EarlierFlag, ...] = ()


@frozen
class JudgeAttribution:
    """Who a charged model call runs as, and which check it belongs to.

    The team pays and its organization's consent is checked; the user is the principal the
    rollout is evaluated for, which for a scheduled check is the alert's creator.
    """

    team: "Team"
    user: "User"
    # Names the scheduled check, and stays the same across retries of it, so the judge can
    # reuse a verdict it already paid for. None for a simulation.
    evaluation_id: str | None = None
    is_agent_billable: bool = True


@frozen
class SeriesJudgment:
    """A judge's answer about the latest point of one series.

    ``fires`` is the model's verdict on the latest point, with the earlier points as its history.
    """

    fires: bool
    kind: AnomalyKind
    rationale: str
    model: str

    def persisted_metadata(self) -> dict[str, Any]:
        """The slice of the judgment worth keeping on the check for a person to read later."""
        return {"rationale": self.rationale, "kind": self.kind}


class SeriesJudge(Protocol):
    """A judge scores a series it understands, at a cost, on someone's behalf.

    It returns None when the series is too short to judge, in which case no call was made.
    A failure to reach a verdict raises ``LLMDetectorError``; a judge never reports "no
    anomaly" because it could not ask.
    """

    def judge_latest(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution
    ) -> SeriesJudgment | None:
        """Judge whether the final point is anomalous, with the rest as its history."""
        ...
