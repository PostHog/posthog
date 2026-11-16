from collections.abc import Callable

import structlog
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.api.oauth.provisioning_review import append_run_log, domain_already_accepted, settle_review
from posthog.egress.firecrawl import FirecrawlNotConfigured
from posthog.llm.system_one import JsonValue, SystemOneNotConfigured
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.cimd_provisioning_review.judgment import (
    RESEARCH_THRESHOLDS,
    SCREEN_THRESHOLDS,
    PartnerJudgment,
    PartnerRegistration,
    judge,
    outcome_for,
)
from posthog.temporal.cimd_provisioning_review.research import research_domain
from posthog.temporal.cimd_provisioning_review.types import (
    CIMDProvisioningReviewInputs,
    ReviewOutcome,
    SettleReviewInputs,
    StageResult,
)

logger = structlog.get_logger(__name__)

_ALREADY_SETTLED = StageResult(outcome=ReviewOutcome.ALREADY_SETTLED, stage="", reason="")

_STATUS_FOR_OUTCOME = {
    ReviewOutcome.ACCEPT: ProvisioningReviewStatus.ACCEPTED,
    ReviewOutcome.REJECT: ProvisioningReviewStatus.REJECTED,
    ReviewOutcome.NEEDS_HUMAN: ProvisioningReviewStatus.NEEDS_HUMAN,
}


def _pending_review(application_id: str) -> CIMDProvisioningReview | None:
    return (
        CIMDProvisioningReview.objects.select_related("application__organization")
        .filter(application_id=application_id, status=ProvisioningReviewStatus.PENDING)
        .first()
    )


def _registration(review: CIMDProvisioningReview) -> PartnerRegistration:
    return PartnerRegistration.from_app(
        review.application, domain=review.domain, metadata_document=review.metadata_document
    )


def _judge(registration: PartnerRegistration, *, evidence: JsonValue = None) -> PartnerJudgment:
    try:
        return judge(registration, evidence=evidence)
    except SystemOneNotConfigured as error:
        # No retry can configure the gateway, so the review goes straight to staff.
        raise ApplicationError(str(error), non_retryable=True) from error


def _logged_step[T](application_id: str, step: str, run: Callable[[], T]) -> T:
    """Run one step and write a failed attempt to the review's run log before Temporal retries it,
    so staff see why a review is slow without opening Temporal."""
    info = activity.info()
    try:
        return run()
    except Exception as error:
        append_run_log(
            application_id,
            step,
            f"Attempt {info.attempt} failed: {error.__class__.__name__}: {error}"[:500],
            level="error",
            attempt=info.attempt,
            workflow_run_id=info.workflow_run_id,
        )
        raise


def _screen(application_id: str) -> StageResult:
    review = _pending_review(application_id)
    if review is None:
        return _ALREADY_SETTLED
    if domain_already_accepted(
        review.domain,
        organization_id=review.application.organization_id,
        excluding_application_id=application_id,
    ):
        reason = f"Another client on {review.domain} from the same organization was accepted"
        append_run_log(application_id, "screen", reason)
        return StageResult(
            outcome=ReviewOutcome.ACCEPT, stage=ProvisioningReviewStage.DOMAIN_ALREADY_ACCEPTED, reason=reason
        )

    judgment = _judge(_registration(review))
    review.screen_judgment = judgment.to_json()
    review.save(update_fields=["screen_judgment"])
    outcome = outcome_for(judgment, SCREEN_THRESHOLDS, unsettled=ReviewOutcome.RESEARCH)
    append_run_log(application_id, "screen", f"Jev: {judgment.describe()}. Next: {outcome.value}")
    logger.info("cimd_provisioning_review_screened", application_id=application_id, outcome=outcome.value)
    return StageResult(outcome=outcome, stage=ProvisioningReviewStage.SCREEN, reason=f"Screen: {judgment.describe()}")


def _research(application_id: str) -> StageResult:
    review = _pending_review(application_id)
    if review is None:
        return _ALREADY_SETTLED

    registration = _registration(review)
    # A retry after a failed judgment reuses the evidence, so it does not pay for the searches again.
    evidence = review.research_evidence
    if evidence is None:
        try:
            found = research_domain(review.domain, homepage_url=registration.homepage_url())
        except FirecrawlNotConfigured as error:
            raise ApplicationError(str(error), non_retryable=True) from error
        evidence = found.to_json()
        review.research_evidence = evidence
        review.save(update_fields=["research_evidence"])
        append_run_log(
            application_id,
            "research",
            (
                f"Homepage {found.homepage.url} {'reachable' if found.homepage.reachable else 'unreachable'}, "
                f"{len(found.about_the_domain.results)} results about the domain, "
                f"{len(found.abuse_reports.results)} results for abuse reports"
            ),
        )

    judgment = _judge(registration, evidence=evidence)
    review.research_judgment = judgment.to_json()
    review.save(update_fields=["research_judgment"])
    outcome = outcome_for(judgment, RESEARCH_THRESHOLDS, unsettled=ReviewOutcome.NEEDS_HUMAN)
    append_run_log(application_id, "research", f"Jev: {judgment.describe()}. Next: {outcome.value}")
    logger.info("cimd_provisioning_review_researched", application_id=application_id, outcome=outcome.value)
    return StageResult(
        outcome=outcome, stage=ProvisioningReviewStage.RESEARCH, reason=f"Research: {judgment.describe()}"
    )


def _settle(inputs: SettleReviewInputs) -> bool:
    status = _STATUS_FOR_OUTCOME.get(inputs.outcome)
    if status is None:
        raise ApplicationError(f"{inputs.outcome} does not settle a review", non_retryable=True)
    return settle_review(
        inputs.application_id,
        status=status,
        stage=ProvisioningReviewStage(inputs.stage),
        reason=inputs.reason,
    )


@activity.defn(name="cimd-provisioning-review-screen")
async def screen_partner(inputs: CIMDProvisioningReviewInputs) -> StageResult:
    return await database_sync_to_async_pool(_logged_step)(
        inputs.application_id, "screen", lambda: _screen(inputs.application_id)
    )


@activity.defn(name="cimd-provisioning-review-research")
async def research_partner(inputs: CIMDProvisioningReviewInputs) -> StageResult:
    return await database_sync_to_async_pool(_logged_step)(
        inputs.application_id, "research", lambda: _research(inputs.application_id)
    )


@activity.defn(name="cimd-provisioning-review-settle")
async def settle_partner_review(inputs: SettleReviewInputs) -> bool:
    return await database_sync_to_async_pool(_settle)(inputs)
