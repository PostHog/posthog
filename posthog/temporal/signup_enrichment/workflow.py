"""Real-time signup enrichment: a fire-and-forget Temporal workflow started after signup.

The workflow wraps the orchestration-agnostic enrichment core (products/growth), writes the
live stores, wires the write-once at-signup snapshot, and emits a launch fill-rate/failure
signal. It is dispatched from the signup request path behind a kill switch and must never
block or fail signup — see posthog/temporal/signup_enrichment/trigger.py.
"""

import json
import typing
import datetime as dt
import dataclasses

from django.db import close_old_connections

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_client
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger

from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider
from products.growth.backend.enrichment.snapshot import SignupEnrichmentSnapshot, capture_signup_enrichment_snapshot
from products.growth.backend.models import OrganizationEnrichment

LOGGER = get_logger(__name__)

ENRICHMENT_SIGNAL_EVENT = "signup_enrichment_completed"

# Hard cap per attempt. The Harmonic client tries up to two domain variations at 30s each,
# so a single lookup can legitimately run ~60s; give it headroom then stop.
ENRICH_ACTIVITY_TIMEOUT = dt.timedelta(seconds=90)

# A couple of retries for transient provider/network blips, then give up quietly. Kept as a
# constant so the activity's failure-signal gate can't drift from the workflow's retry policy.
MAX_ENRICH_ATTEMPTS = 3


@dataclasses.dataclass
class SignupEnrichmentInputs:
    organization_id: str
    distinct_id: str
    domain: str


def _deterministic_company_type(organization_id: str) -> typing.Optional[str]:
    """The classifier's at-signup value, if the signup hook has written it."""
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
    if record is None:
        return None
    value = record.data.get("company_type_deterministic")
    return value if isinstance(value, str) else None


@activity.defn
async def enrich_signup_organization_activity(inputs: SignupEnrichmentInputs) -> dict[str, typing.Any]:
    """Enrich one organization by domain, persist, snapshot, and emit the launch signal."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415 — heavy import kept off the workflow module path

    close_old_connections()
    logger = LOGGER.bind(organization_id=inputs.organization_id)
    pha_client = get_client()

    try:
        fields = await enrich_organization(
            organization_id=inputs.organization_id,
            domain=inputs.domain,
            provider=HarmonicEnrichmentProvider(),
            pha_client=pha_client,
        )
        filled = fields.to_dict() if fields else {}

        deterministic = await sync_to_async(_deterministic_company_type)(inputs.organization_id)
        snapshot = SignupEnrichmentSnapshot(
            company_type=(fields.company_type if fields else None) or deterministic,
            headcount=fields.headcount if fields else None,
            headcount_engineering=fields.headcount_engineering if fields else None,
            industry=fields.industry if fields else None,
            country=fields.country if fields else None,
            founded_year=fields.founded_year if fields else None,
            funding_stage=fields.funding_stage if fields else None,
            is_yc_company=fields.is_yc_company if fields else None,
        )
        await sync_to_async(capture_signup_enrichment_snapshot)(
            pha_client,
            organization_id=inputs.organization_id,
            distinct_id=inputs.distinct_id,
            snapshot=snapshot,
        )

        if pha_client is not None:
            pha_client.capture(
                distinct_id=inputs.distinct_id,
                event=ENRICHMENT_SIGNAL_EVENT,
                properties={"success": True, "matched": fields is not None, "fields_filled": sorted(filled.keys())},
                groups={"organization": inputs.organization_id},
            )
        logger.info("signup_enrichment_completed", matched=fields is not None, fields_filled=len(filled))
        return {"matched": fields is not None, "fields_filled": len(filled)}

    except Exception as e:
        capture_exception(e)
        # Emit the failure signal only once retries are exhausted; a transient error that a later
        # attempt recovers from must not count against the launch fill-rate/failure signal.
        if pha_client is not None and activity.info().attempt >= MAX_ENRICH_ATTEMPTS:
            pha_client.capture(
                distinct_id=inputs.distinct_id,
                event=ENRICHMENT_SIGNAL_EVENT,
                properties={"success": False, "error": type(e).__name__},
                groups={"organization": inputs.organization_id},
            )
        raise
    finally:
        if pha_client is not None:
            pha_client.shutdown()


@workflow.defn(name="signup-enrichment")
class SignupEnrichmentWorkflow(PostHogWorkflow):
    """Fire-and-forget enrichment for one organization, started right after signup."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SignupEnrichmentInputs:
        return SignupEnrichmentInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: SignupEnrichmentInputs) -> dict[str, typing.Any]:
        return await workflow.execute_activity(
            enrich_signup_organization_activity,
            inputs,
            start_to_close_timeout=ENRICH_ACTIVITY_TIMEOUT,
            # Onboarding routing already degrades to a safe default when enrichment is absent.
            retry_policy=RetryPolicy(maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)),
        )
