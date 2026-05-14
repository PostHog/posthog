import json
import typing
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings
from django.db import close_old_connections

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)

ENRICHED_EVENT_NAME = "organization_enriched"
ENRICHED_GROUP_TYPE = "organization"
DEFAULT_CHUNK_SIZE = 25
ENRICHMENT_CONCURRENCY = 5

FIELD_NAME = "$enriched_org_name"
FIELD_DOMAIN = "$enriched_org_domain"
FIELD_DESCRIPTION = "$enriched_org_description"
FIELD_HEADCOUNT = "$enriched_org_headcount"
FIELD_HEADQUARTERS = "$enriched_org_headquarters"
FIELD_LOCATION_CITY = "$enriched_org_city"
FIELD_LOCATION_STATE = "$enriched_org_state"
FIELD_LOCATION_COUNTRY = "$enriched_org_country"
FIELD_FOUNDED_YEAR = "$enriched_org_founded_year"
FIELD_FUNDING_STAGE = "$enriched_org_funding_stage"
FIELD_LAST_FUNDING_TYPE = "$enriched_org_last_funding_type"
FIELD_LAST_FUNDING_AMOUNT = "$enriched_org_last_funding_amount"
FIELD_LAST_FUNDING_AT = "$enriched_org_last_funding_at"
FIELD_FUNDING_TOTAL = "$enriched_org_funding_total"
FIELD_FUNDING_ROUNDS = "$enriched_org_num_funding_rounds"
FIELD_WEB_TRAFFIC = "$enriched_org_web_traffic_latest"
FIELD_LINKEDIN_FOLLOWERS = "$enriched_org_linkedin_followers"
FIELD_TWITTER_FOLLOWERS = "$enriched_org_twitter_followers"


@dataclasses.dataclass
class OrganizationTarget:
    organization_id: str
    domain: str
    # Optional context fields that can come from the source list. Not required
    # for enrichment but carried through so the emitted event can reference them.
    name: str | None = None


@dataclasses.dataclass
class OrganizationEnrichmentInputs:
    targets: list[OrganizationTarget]
    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_targets: int | None = None  # Optional cap for testing.


@dataclasses.dataclass
class EnrichOrganizationChunkInputs:
    targets: list[OrganizationTarget]


def _str_or_none(value: typing.Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _extract_year(date_str: typing.Any) -> int | None:
    if not isinstance(date_str, str) or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def _extract_harmonic_fields(harmonic_data: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Map a Harmonic `enrichCompanyByIdentifiers.company` response into the
    curated `$enriched_org_*` set we store on the PostHog group.

    The exact response shape is locked in by the GraphQL query at
    `ee/billing/salesforce_enrichment/constants.py::HARMONIC_COMPANY_ENRICHMENT_QUERY`
    — when fields are missing we surface `None` rather than empty strings."""
    website = harmonic_data.get("website") or {}
    location = harmonic_data.get("location") or {}
    founding = harmonic_data.get("foundingDate") or {}
    funding = harmonic_data.get("funding") or {}
    traction = harmonic_data.get("tractionMetrics") or {}

    def _latest(metric_key: str) -> typing.Any:
        metric = traction.get(metric_key) or {}
        return metric.get("latestMetricValue")

    city = _str_or_none(location.get("city"))
    state = _str_or_none(location.get("state"))
    country = _str_or_none(location.get("country"))
    headquarters = ", ".join(part for part in (city, state, country) if part) or None

    return {
        FIELD_NAME: _str_or_none(harmonic_data.get("name")),
        FIELD_DOMAIN: _str_or_none(website.get("domain")),
        FIELD_DESCRIPTION: _str_or_none(harmonic_data.get("description")),
        FIELD_HEADCOUNT: harmonic_data.get("headcount"),
        FIELD_HEADQUARTERS: headquarters,
        FIELD_LOCATION_CITY: city,
        FIELD_LOCATION_STATE: state,
        FIELD_LOCATION_COUNTRY: country,
        FIELD_FOUNDED_YEAR: _extract_year(founding.get("date")),
        FIELD_FUNDING_STAGE: _str_or_none(funding.get("fundingStage")),
        FIELD_LAST_FUNDING_TYPE: _str_or_none(funding.get("lastFundingType")),
        FIELD_LAST_FUNDING_AMOUNT: funding.get("lastFundingTotal"),
        FIELD_LAST_FUNDING_AT: _str_or_none(funding.get("lastFundingAt")),
        FIELD_FUNDING_TOTAL: funding.get("fundingTotal"),
        FIELD_FUNDING_ROUNDS: funding.get("numFundingRounds"),
        FIELD_WEB_TRAFFIC: _latest("webTraffic"),
        FIELD_LINKEDIN_FOLLOWERS: _latest("linkedinFollowerCount"),
        FIELD_TWITTER_FOLLOWERS: _latest("twitterFollowerCount"),
    }


def _build_capture_client() -> typing.Any | None:
    """PostHog SDK client used to emit `$groupidentify` + `organization_enriched`
    events. Returns None when no project API key is configured (workflow then
    only writes to PostHog without emitting events — useful for dry runs)."""
    from posthoganalytics import Posthog

    cloud_token = settings.PEOPLE_ENRICHMENT_POSTHOG_API_KEY
    if not cloud_token:
        return None
    return Posthog(cloud_token, host=settings.PEOPLE_ENRICHMENT_POSTHOG_HOST, sync_mode=True)


async def enrich_organization_chunk(inputs: EnrichOrganizationChunkInputs) -> dict[str, typing.Any]:
    """Enrich one chunk of organizations via Harmonic and emit events to PostHog.

    Pure async helper with no Temporal runtime dependency so it can be invoked
    from management commands and tests in addition to the wrapping activity.
    """
    close_old_connections()

    from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient

    capture_client = _build_capture_client()
    enriched_count = 0
    no_match_count = 0
    errors: list[str] = []

    async with AsyncHarmonicClient() as harmonic:
        semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)

        async def _enrich_one(
            target: OrganizationTarget,
        ) -> tuple[OrganizationTarget, dict[str, typing.Any] | None, str | None]:
            async with semaphore:
                try:
                    data = await harmonic.enrich_company_by_domain(target.domain)
                except Exception as e:
                    return target, None, str(e)
                if data is None:
                    return target, None, None
                return target, _extract_harmonic_fields(data), None

        results = await asyncio.gather(*(_enrich_one(t) for t in inputs.targets))

    def _emit(target: OrganizationTarget, fields: dict[str, typing.Any]) -> None:
        if not capture_client:
            return
        non_null_fields = {k: v for k, v in fields.items() if v is not None}
        # `$groupidentify` updates the group's properties via the ingestion
        # pipeline (equivalent to `posthog.set` but for groups).
        capture_client.group_identify(
            group_type=ENRICHED_GROUP_TYPE,
            group_key=target.organization_id,
            properties=non_null_fields,
        )
        # An `organization_enriched` event keyed to the group via `$groups` so
        # the enrichment is queryable in product analytics breakdowns/funnels.
        capture_client.capture(
            distinct_id=target.organization_id,
            event=ENRICHED_EVENT_NAME,
            properties={
                "enriched_fields": sorted(non_null_fields.keys()),
                "$groups": {ENRICHED_GROUP_TYPE: target.organization_id},
                "organization_domain": target.domain,
                **non_null_fields,
            },
        )

    for target, fields, err in results:
        if err is not None:
            errors.append(f"{target.organization_id} ({target.domain}): {err}")
            continue
        if fields is None:
            no_match_count += 1
            continue
        # `_emit` issues two synchronous HTTP calls via the PostHog SDK
        # (`sync_mode=True`). Running it directly here would block the asyncio
        # event loop for ~2 round-trips per matched org; offload to a thread.
        await asyncio.to_thread(_emit, target, fields)
        enriched_count += 1

    if capture_client is not None:
        await asyncio.to_thread(capture_client.shutdown)

    LOGGER.info(
        "Enriched organization chunk",
        processed=len(inputs.targets),
        enriched=enriched_count,
        no_match=no_match_count,
        errors=len(errors),
    )

    return {
        "processed": len(inputs.targets),
        "enriched": enriched_count,
        "no_match": no_match_count,
        "errors": errors,
    }


@activity.defn
async def enrich_organization_chunk_activity(inputs: EnrichOrganizationChunkInputs) -> dict[str, typing.Any]:
    async with Heartbeater():
        return await enrich_organization_chunk(inputs)


@workflow.defn(name="organization-enrichment-harmonic")
class OrganizationEnrichmentWorkflow(PostHogWorkflow):
    """Bulk-enrich PostHog organizations via Harmonic, writing the curated set
    onto the corresponding group (keyed by `organization_id`) and emitting an
    `organization_enriched` event per match."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> OrganizationEnrichmentInputs:
        loaded = json.loads(inputs[0])
        raw_targets = loaded.pop("targets", [])
        targets = [OrganizationTarget(**t) for t in raw_targets]
        return OrganizationEnrichmentInputs(targets=targets, **loaded)

    @workflow.run
    async def run(self, inputs: OrganizationEnrichmentInputs) -> dict[str, typing.Any]:
        logger = LOGGER.bind(target_count=len(inputs.targets))
        logger.info("Starting organization enrichment workflow", chunk_size=inputs.chunk_size)

        targets = inputs.targets
        if inputs.max_targets is not None:
            targets = targets[: inputs.max_targets]

        totals = {"processed": 0, "enriched": 0, "no_match": 0, "errors": 0}
        sample_errors: list[str] = []

        for chunk_start in range(0, len(targets), inputs.chunk_size):
            chunk = targets[chunk_start : chunk_start + inputs.chunk_size]
            result = await workflow.execute_activity(
                enrich_organization_chunk_activity,
                EnrichOrganizationChunkInputs(targets=chunk),
                start_to_close_timeout=dt.timedelta(minutes=15),
                retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=5), maximum_attempts=3),
                heartbeat_timeout=dt.timedelta(minutes=2),
            )

            totals["processed"] += result.get("processed", 0)
            totals["enriched"] += result.get("enriched", 0)
            totals["no_match"] += result.get("no_match", 0)
            chunk_errors = result.get("errors", []) or []
            totals["errors"] += len(chunk_errors)
            sample_errors.extend(chunk_errors[: max(0, 10 - len(sample_errors))])

        return {
            **totals,
            "sample_errors": sample_errors,
        }
