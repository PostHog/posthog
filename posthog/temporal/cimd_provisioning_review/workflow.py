from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError

from posthog.models.oauth_provisioning_review import ProvisioningReviewStage
from posthog.temporal.cimd_provisioning_review.activities import research_partner, settle_partner_review
from posthog.temporal.cimd_provisioning_review.types import (
    CIMDProvisioningReviewInputs,
    ReviewOutcome,
    SettleReviewInputs,
    StageResult,
)
from posthog.temporal.common.base import PostHogWorkflow

# Spaced out so an ai-gateway or Firecrawl outage of several minutes still ends in a verdict.
_JUDGING_RETRY = common.RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=6,
)
_SETTLE_RETRY = common.RetryPolicy(initial_interval=timedelta(seconds=5), maximum_attempts=10)


@workflow.defn(name="cimd-provisioning-review")
class CIMDProvisioningReviewWorkflow(PostHogWorkflow):
    """Researches a self-registered provisioning partner on the web, has Jev judge it with that
    evidence, and settles the review. A pipeline failure hands the review to staff, so the partner
    never stays pending with nothing working on it."""

    inputs_cls = CIMDProvisioningReviewInputs

    @workflow.run
    async def run(self, inputs: CIMDProvisioningReviewInputs) -> str:
        try:
            result: StageResult = await workflow.execute_activity(
                research_partner,
                inputs,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=_JUDGING_RETRY,
            )
        except ActivityError as error:
            workflow.logger.warning(
                "cimd provisioning review pipeline failed",
                extra={"application_id": inputs.application_id, **self._activity_error_properties(error)},
            )
            result = StageResult(
                outcome=ReviewOutcome.NEEDS_HUMAN,
                stage=ProvisioningReviewStage.PIPELINE_FAILED,
                reason=f"The review pipeline failed at {error.activity_type}",
            )

        if result.outcome == ReviewOutcome.ALREADY_SETTLED:
            return result.outcome.value

        await workflow.execute_activity(
            settle_partner_review,
            SettleReviewInputs(
                application_id=inputs.application_id,
                outcome=result.outcome,
                stage=result.stage,
                reason=result.reason,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_SETTLE_RETRY,
        )
        return result.outcome.value
