import json
import math
import typing
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings
from django.db import close_old_connections

from asgiref.sync import sync_to_async
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
class _OrganizationRow:
    """Loaded from `posthog_organization` joined with the picked
    `posthog_organizationdomain` row."""

    organization_id: str
    name: str | None
    domain: str


@dataclasses.dataclass
class OrganizationEnrichmentInputs:
    """Workflow inputs for org enrichment.

    Mirrors the people workflow: the workflow pulls candidates from the local
    `posthog_organization` table directly. There's no `$enriched_at`-style
    dedupe field on the `Organization` model, so re-runs over the same offset
    will re-enrich already-enriched orgs and burn Harmonic credits. Until a
    dedupe column exists, callers should bound runs with `max_chunks`."""

    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_chunks: int | None = None
    # Optional explicit allow-list. When provided, only orgs whose UUID is in
    # this list get enriched (handy for ad-hoc re-runs or scoped backfills).
    organization_ids: list[str] | None = None


@dataclasses.dataclass
class EnrichOrganizationChunkInputs:
    offset: int
    chunk_size: int
    organization_ids: list[str] | None = None


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


def _build_orgs_queryset(organization_ids: list[str] | None) -> typing.Any:
    """`Organization`s with a domain attached, deterministically ordered.

    Each Organization can have several `OrganizationDomain` rows; we pick one
    via a `Subquery` that prefers verified domains (most recent verification
    wins) and falls back to whichever row sorts first by id. Orgs with no
    domain at all are filtered out — there's nothing to enrich without one."""
    from django.db.models import OuterRef, Subquery

    from posthog.models import Organization
    from posthog.models.organization_domain import OrganizationDomain

    domain_subquery = (
        OrganizationDomain.objects.filter(organization=OuterRef("pk"))
        .order_by("-verified_at", "id")
        .values("domain")[:1]
    )
    qs = Organization.objects.annotate(picked_domain=Subquery(domain_subquery)).filter(picked_domain__isnull=False)
    if organization_ids:
        qs = qs.filter(id__in=organization_ids)
    return qs.order_by("id")


@activity.defn
async def count_organizations_activity(organization_ids: list[str] | None = None) -> int:
    """Count org-table rows that the workflow would enrich (mirrors `_load_page`)."""
    close_old_connections()
    qs = _build_orgs_queryset(organization_ids)
    return await sync_to_async(qs.count)()


async def enrich_organization_chunk(inputs: EnrichOrganizationChunkInputs) -> dict[str, typing.Any]:
    """Enrich one page of `posthog_organization` rows via Harmonic and emit
    events to PostHog. Pure async helper with no Temporal runtime dependency
    so it can be invoked from management commands and tests in addition to the
    wrapping activity."""
    close_old_connections()

    from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient

    capture_client = _build_capture_client()
    # Org enrichment's only persistence path is the PostHog capture client
    # (no local DB write — groups live in the target project). Fail loudly
    # rather than spinning up Harmonic, paying for the lookup, and then
    # silently dropping every result while still reporting `enriched: N`.
    if capture_client is None:
        raise RuntimeError(
            "Cannot run organization enrichment without a capture client — "
            "set PEOPLE_ENRICHMENT_POSTHOG_API_KEY so the workflow has somewhere "
            "to write `$groupidentify` + `organization_enriched` events."
        )

    def _load_page() -> list[_OrganizationRow]:
        qs = _build_orgs_queryset(inputs.organization_ids)[inputs.offset : inputs.offset + inputs.chunk_size]
        return [_OrganizationRow(organization_id=str(org.id), name=org.name, domain=org.picked_domain) for org in qs]

    rows = await sync_to_async(_load_page)()
    if not rows:
        return {"processed": 0, "enriched": 0, "no_match": 0, "errors": []}

    enriched_count = 0
    no_match_count = 0
    errors: list[str] = []

    async with AsyncHarmonicClient() as harmonic:
        semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)

        async def _enrich_one(
            row: _OrganizationRow,
        ) -> tuple[_OrganizationRow, dict[str, typing.Any] | None, str | None]:
            async with semaphore:
                try:
                    data = await harmonic.enrich_company_by_domain(row.domain)
                except Exception as e:
                    return row, None, str(e)
                if data is None:
                    return row, None, None
                return row, _extract_harmonic_fields(data), None

        results = await asyncio.gather(*(_enrich_one(r) for r in rows))

    def _emit(row: _OrganizationRow, fields: dict[str, typing.Any]) -> None:
        non_null_fields = {k: v for k, v in fields.items() if v is not None}
        # `$groupidentify` updates the group's properties via the ingestion
        # pipeline (equivalent to `posthog.set` but for groups).
        capture_client.group_identify(
            group_type=ENRICHED_GROUP_TYPE,
            group_key=row.organization_id,
            properties=non_null_fields,
        )
        # An `organization_enriched` event keyed to the group via `$groups` so
        # the enrichment is queryable in product analytics breakdowns/funnels.
        capture_client.capture(
            distinct_id=row.organization_id,
            event=ENRICHED_EVENT_NAME,
            properties={
                "enriched_fields": sorted(non_null_fields.keys()),
                "$groups": {ENRICHED_GROUP_TYPE: row.organization_id},
                "organization_domain": row.domain,
                **non_null_fields,
            },
        )

    for row, fields, err in results:
        if err is not None:
            errors.append(f"{row.organization_id} ({row.domain}): {err}")
            continue
        if fields is None:
            no_match_count += 1
            continue
        # `_emit` issues two synchronous HTTP calls via the PostHog SDK
        # (`sync_mode=True`). Running it directly here would block the asyncio
        # event loop for ~2 round-trips per matched org; offload to a thread.
        await asyncio.to_thread(_emit, row, fields)
        enriched_count += 1

    await asyncio.to_thread(capture_client.shutdown)

    LOGGER.info(
        "Enriched organization chunk",
        processed=len(rows),
        enriched=enriched_count,
        no_match=no_match_count,
        errors=len(errors),
    )

    return {
        "processed": len(rows),
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
    """Bulk-enrich PostHog organizations from `posthog_organization` via
    Harmonic. Writes the curated set onto the corresponding group (keyed by
    `organization_id`) and emits an `organization_enriched` event per match.

    Pagination is offset-based against a deterministically-ordered query of
    orgs that have a domain attached. The candidate set does NOT shrink across
    chunks (no `$enriched_at` field exists on `Organization`), so callers
    should cap iteration with `max_chunks` to avoid re-enrichment on subsequent
    runs."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> OrganizationEnrichmentInputs:
        loaded = json.loads(inputs[0])
        return OrganizationEnrichmentInputs(**loaded)

    @workflow.run
    async def run(self, inputs: OrganizationEnrichmentInputs) -> dict[str, typing.Any]:
        logger = LOGGER.bind()
        logger.info(
            "Starting organization enrichment workflow",
            chunk_size=inputs.chunk_size,
            max_chunks=inputs.max_chunks,
            organization_ids=len(inputs.organization_ids) if inputs.organization_ids else None,
        )

        total = await workflow.execute_activity(
            count_organizations_activity,
            inputs.organization_ids,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        estimated_chunks = math.ceil(total / inputs.chunk_size) if total else 0
        logger.info("Found enrichment targets", total=total, estimated_chunks=estimated_chunks)

        offset = 0
        chunks_completed = 0
        totals = {"processed": 0, "enriched": 0, "no_match": 0, "errors": 0}
        sample_errors: list[str] = []

        while True:
            if inputs.max_chunks is not None and chunks_completed >= inputs.max_chunks:
                break

            result = await workflow.execute_activity(
                enrich_organization_chunk_activity,
                EnrichOrganizationChunkInputs(
                    offset=offset,
                    chunk_size=inputs.chunk_size,
                    organization_ids=inputs.organization_ids,
                ),
                start_to_close_timeout=dt.timedelta(minutes=15),
                retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=5), maximum_attempts=3),
                heartbeat_timeout=dt.timedelta(minutes=2),
            )

            processed = result.get("processed", 0)
            totals["processed"] += processed
            totals["enriched"] += result.get("enriched", 0)
            totals["no_match"] += result.get("no_match", 0)
            chunk_errors = result.get("errors", []) or []
            totals["errors"] += len(chunk_errors)
            sample_errors.extend(chunk_errors[: max(0, 10 - len(sample_errors))])

            chunks_completed += 1

            if processed < inputs.chunk_size:
                break

            offset += inputs.chunk_size

        return {
            "chunks_processed": chunks_completed,
            **totals,
            "sample_errors": sample_errors,
        }
