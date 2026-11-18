from enum import StrEnum

from posthog.dataclasses import frozen


class ReviewOutcome(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    NEEDS_HUMAN = "needs_human"
    # The review was settled before this run reached it, by staff or by an earlier run.
    ALREADY_SETTLED = "already_settled"


@frozen
class CIMDProvisioningReviewInputs:
    application_id: str


@frozen
class StageResult:
    outcome: ReviewOutcome
    stage: str
    reason: str


@frozen
class SettleReviewInputs:
    application_id: str
    outcome: ReviewOutcome
    stage: str
    reason: str
