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

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_client
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import aretry_on_db_connection_drop, close_db_connections

from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider
from products.growth.backend.enrichment.snapshot import SignupEnrichmentSnapshot, capture_signup_enrichment_snapshot
from products.growth.backend.models import OrganizationEnrichment

LOGGER = get_logger(__name__)

ENRICHMENT_SIGNAL_EVENT = "signup_enrichment_completed"
ENRICHMENT_RECHECK_EVENT = "signup_enrichment_recheck"

# Hard cap per attempt. The Harmonic client tries up to two domain variations at 30s each,
# so a single lookup can legitimately run ~60s; give it headroom then stop.
ENRICH_ACTIVITY_TIMEOUT = dt.timedelta(seconds=90)

# A couple of retries for transient provider/network blips, then give up quietly. Kept as a
# constant so the activity's failure-signal gate can't drift from the workflow's retry policy.
MAX_ENRICH_ATTEMPTS = 3

# Harmonic's enrich mutation seeds async enrichment for a company it doesn't yet index, so a
# domain it can't match at signup often resolves a few hours later. One delayed recheck recovers
# those late-indexed companies without polling.
RECHECK_DELAY = dt.timedelta(hours=4)


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
@close_db_connections
async def enrich_signup_organization_activity(
    inputs: SignupEnrichmentInputs, is_recheck: bool = False
) -> dict[str, typing.Any]:
    """Enrich one organization by domain and persist it to the live stores.

    First attempt (is_recheck=False): also captures the write-once at-signup snapshot and emits
    the launch signal. The recheck (is_recheck=True) writes the live stores exactly like a first
    attempt but leaves the snapshot and the launch signal untouched — the snapshot is at-signup by
    design, and the launch alert reads only the first attempt — emitting its own recheck event.
    """
    from asgiref.sync import sync_to_async  # noqa: PLC0415 — heavy import kept off the workflow module path

    logger = LOGGER.bind(organization_id=inputs.organization_id, is_recheck=is_recheck)

    if is_recheck:
        # The org owner can delete the org during the recheck delay; without this guard the
        # recheck would enrich a deleted org (db_constraint=False means orphan rows, and the
        # group projection would write properties for a dead org).
        from posthog.models import Organization  # noqa: PLC0415 — heavy import kept off the workflow module path

        # The pooled connection has been idle through the 4h recheck delay, so it may have been
        # recycled by pgbouncer / CONN_MAX_AGE / failover; retry once on a dropped connection.
        org_exists = await aretry_on_db_connection_drop(
            lambda: sync_to_async(Organization.objects.filter(id=inputs.organization_id).exists)()
        )
        if not org_exists:
            logger.info("signup_enrichment_recheck_skipped_org_deleted")
            return {"matched": False, "fields_filled": 0, "org_deleted": True}

    pha_client = get_client()

    try:
        fields = await enrich_organization(
            organization_id=inputs.organization_id,
            domain=inputs.domain,
            provider=HarmonicEnrichmentProvider(),
            pha_client=pha_client,
            is_recheck=is_recheck,
        )
        filled = fields.to_dict() if fields else {}
        matched = fields is not None

        if not is_recheck:
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
            if is_recheck:
                pha_client.capture(
                    distinct_id=inputs.distinct_id,
                    event=ENRICHMENT_RECHECK_EVENT,
                    properties={
                        "upgraded": matched,
                        "fields_filled": len(filled),
                        "organization_id": inputs.organization_id,
                    },
                    groups={"organization": inputs.organization_id},
                )
            else:
                pha_client.capture(
                    distinct_id=inputs.distinct_id,
                    event=ENRICHMENT_SIGNAL_EVENT,
                    properties={"success": True, "matched": matched, "fields_filled": sorted(filled.keys())},
                    groups={"organization": inputs.organization_id},
                )
        logger.info("signup_enrichment_completed", matched=matched, fields_filled=len(filled))
        return {"matched": matched, "fields_filled": len(filled)}

    except Exception as e:
        capture_exception(e)
        # Emit the failure signal only on a first attempt whose retries are exhausted; a transient
        # error a later attempt recovers from, and any recheck failure, must not count against the
        # launch fill-rate/failure signal.
        if not is_recheck and pha_client is not None and activity.info().attempt >= MAX_ENRICH_ATTEMPTS:
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
        result = await self._enrich(inputs, is_recheck=False)
        if result.get("matched"):
            return result

        # Give Harmonic's seeded async enrichment time to index the company, then look once more.
        await workflow.sleep(RECHECK_DELAY)
        return await self._enrich(inputs, is_recheck=True)

    async def _enrich(self, inputs: SignupEnrichmentInputs, *, is_recheck: bool) -> dict[str, typing.Any]:
        return await workflow.execute_activity(
            enrich_signup_organization_activity,
            args=[inputs, is_recheck],
            start_to_close_timeout=ENRICH_ACTIVITY_TIMEOUT,
            # Onboarding routing already degrades to a safe default when enrichment is absent.
            retry_policy=RetryPolicy(maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)),
        )
