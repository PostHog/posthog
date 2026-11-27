"""An AND ensemble that has the AI judge as one member, with the judge asked only when it can change the flag.

``EnsembleDetector`` runs every member on every check, so an AI member there would make a model call per
check, and the judge is not a ``BaseDetector`` anyway. Here the caller runs the local members, through the
registry, and asks the judge only about a bucket that they flag. For AND, a skipped call gives the same flag
as a made call.

This module stays light, like ``contract``: the facade re-exports from it, and the model client loads only
when a call is made.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

from posthog.schema import DetectorType

from posthog.dataclasses import frozen

from products.alerts.backend.judge.contract import (
    JudgeAttribution,
    LLMDetectorError,
    LLMDetectorPausedError,
    SeriesContext,
    SeriesJudgment,
)

if TYPE_CHECKING:
    from posthog.models.team import Team

# The longest one judge call can take: the model call's 60-second timeout, its one in-request retry,
# and the wait for a model-call slot. See `REQUEST_TIMEOUT_SECONDS` in `judge/llm.py`.
MAX_JUDGE_CALL_SECONDS = 2 * 60 + 5


class MemberState(StrEnum):
    FIRED = "fired"
    NOT_FIRED = "not_fired"
    # The member was not asked. For the AI member, the reason says why.
    NOT_EVALUATED = "not_evaluated"


class NotEvaluatedReason(StrEnum):
    # The local members did not flag the bucket, so the judge could not change the flag.
    LOCAL_NOT_FIRED = "local_not_fired"
    # The caller's cap on calls was reached.
    CAP = "cap"
    # The caller's time for calls ran out.
    TIME_BUDGET = "time_budget"
    # The judge refused to call: no AI data processing consent, no AI credits, or a model that is no longer offered.
    PAUSED = "paused"
    # The model call failed, timed out, or returned a verdict the judge could not read.
    UNAVAILABLE = "unavailable"
    # The series is too short to send to the model.
    TOO_SHORT = "too_short"


@frozen
class LazyAndEnsemble:
    """A detector config split into the part the registry runs and the AI member, if any."""

    # A registry detector config: one detector, or an ensemble of the local members.
    local: dict[str, Any]
    judge: dict[str, Any] | None = None


@frozen
class JudgeMemberResult:
    state: MemberState
    judgment: SeriesJudgment | None = None
    reason: NotEvaluatedReason | None = None

    def details(self) -> dict[str, Any]:
        """The member result to store with the bucket: its state, and the judge's rationale, kind and model."""
        details: dict[str, Any] = {"type": DetectorType.LLM.value, "state": self.state.value}
        if self.judgment is not None:
            details.update(self.judgment.persisted_metadata())
        if self.reason is not None:
            details["reason"] = self.reason.value
        return details


def is_ai_member(config: Any) -> bool:
    return isinstance(config, dict) and config.get("type") == DetectorType.LLM.value


def split_ai_member(config: dict[str, Any]) -> LazyAndEnsemble:
    """Split an ensemble config into its local part and its AI member.

    An AI member is valid only in an ensemble with ``operator: "and"``, at most once, and next to at least
    one local member. With ``or``, the judge would run on every check. With one local member left, the
    local part is that detector alone. A config with no AI member is returned unchanged.
    """
    if is_ai_member(config):
        raise ValueError("The AI detector needs a local detector to run first.")
    members = config.get("detectors")
    if config.get("type") != "ensemble" or not isinstance(members, list):
        return LazyAndEnsemble(local=config)
    judges = [member for member in members if is_ai_member(member)]
    if not judges:
        return LazyAndEnsemble(local=config)
    if len(judges) > 1:
        raise ValueError("An ensemble can have at most one AI detector.")
    if config.get("operator", "and") != "and":
        raise ValueError('An ensemble with the AI detector must use operator "and".')
    local = [member for member in members if not is_ai_member(member)]
    if not local:
        raise ValueError("The AI detector needs a local detector to run first.")
    return LazyAndEnsemble(
        local=local[0] if len(local) == 1 else {**config, "detectors": local},
        judge=judges[0],
    )


def not_evaluated(reason: NotEvaluatedReason) -> JudgeMemberResult:
    return JudgeMemberResult(state=MemberState.NOT_EVALUATED, reason=reason)


def judge_flagged_bucket(
    judge_config: dict[str, Any],
    data: np.ndarray,
    *,
    series: SeriesContext,
    team: "Team",
    evaluation_id: str,
    ai_product: str,
) -> JudgeMemberResult:
    """Ask the judge about the last point of ``data``, which the local members flagged.

    Runs with no person: the caller's own rollout gates it, and the judge checks the organization's AI data
    processing consent. The call is not billable to the customer. A failure to reach a verdict returns a
    not evaluated result instead of raising, so the caller keeps the local flag.
    """
    from products.alerts.backend.judge.llm import LLMSeriesJudge  # noqa: PLC0415 — loads the model client

    attribution = JudgeAttribution(
        team=team, user=None, evaluation_id=evaluation_id, is_agent_billable=False, ai_product=ai_product
    )
    try:
        judgment = LLMSeriesJudge(judge_config).judge_latest(data, series=series, attribution=attribution)
    except LLMDetectorPausedError:
        return not_evaluated(NotEvaluatedReason.PAUSED)
    except LLMDetectorError:
        return not_evaluated(NotEvaluatedReason.UNAVAILABLE)
    if judgment is None:
        return not_evaluated(NotEvaluatedReason.TOO_SHORT)
    return JudgeMemberResult(
        state=MemberState.FIRED if judgment.fires else MemberState.NOT_FIRED,
        judgment=judgment,
    )


def combined_flag(local_flag: bool, judge: JudgeMemberResult) -> bool:
    """The AND of the members. An AI member that was not asked keeps the local flag."""
    return local_flag and judge.state != MemberState.NOT_FIRED
