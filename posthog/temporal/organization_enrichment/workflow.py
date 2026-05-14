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
ENRICHED_AT_KEY = "$enriched_at"
DEFAULT_GROUP_TYPE = "organization"
DEFAULT_DOMAIN_PROPERTY = "domain"
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
class _GroupRow:
    """One `posthog_group` row's worth of enrichment input."""

    pk: int
    group_key: str
    domain: str


@dataclasses.dataclass
class OrganizationEnrichmentInputs:
    """Workflow inputs for org enrichment.

    Production trigger: a customer kicks off a backfill from a button in their
    PostHog project. We enrich every `posthog_group` row (of the chosen group
    type) in that project's team that has a domain attached and hasn't been
    enriched yet. Dedupe is via `$enriched_at` in `group_properties`, stamped
    on every attempt — match, no-match, or error."""

    team_id: int
    # The customer's group type name. Different projects use different
    # taxonomies — most use `organization`, some use `company`/`workspace`.
    group_type: str = DEFAULT_GROUP_TYPE
    # Where to find the company domain in `group_properties`. Most SDK
    # integrations set `domain`; some use `website` or a custom key.
    domain_property: str = DEFAULT_DOMAIN_PROPERTY
    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_chunks: int | None = None
    reenrich: bool = False


@dataclasses.dataclass
class EnrichOrganizationChunkInputs:
    team_id: int
    group_type: str
    domain_property: str
    chunk_size: int
    reenrich: bool


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


def _resolve_group_type_index(team_id: int, group_type: str) -> int | None:
    """Resolve a group type name (e.g. `organization`) to its per-team index.

    Group-type indexes are per-team — what's `organization` in one project may
    not be the same index in another. Returns None when the team has no such
    type configured, in which case there's nothing to enrich."""
    from posthog.models.group_type_mapping import GroupTypeMapping

    mapping = GroupTypeMapping.objects.filter(team_id=team_id, group_type=group_type).first()
    return mapping.group_type_index if mapping is not None else None


def _build_groups_queryset(team_id: int, group_type_index: int, domain_property: str, reenrich: bool) -> typing.Any:
    """Groups for the team + type that still need enrichment.

    Candidates must have a domain attached at `group_properties[<domain_property>]`;
    `ENRICHED_AT_KEY` exclusion implements dedupe (the chunk's persist step
    stamps it on every attempt, so the candidate set strictly shrinks)."""
    from posthog.models import Group

    qs = Group.objects.filter(
        team_id=team_id,
        group_type_index=group_type_index,
        group_properties__has_key=domain_property,
    )
    if not reenrich:
        qs = qs.exclude(group_properties__has_key=ENRICHED_AT_KEY)
    return qs.order_by("group_key")


@activity.defn
async def count_organizations_activity(
    team_id: int,
    group_type: str = DEFAULT_GROUP_TYPE,
    domain_property: str = DEFAULT_DOMAIN_PROPERTY,
    reenrich: bool = False,
) -> int:
    """Count groups that the workflow would enrich. Mirrors `_load_page`'s
    filter exactly so the `estimated_chunks` log line is honest."""
    close_old_connections()
    group_type_index = await sync_to_async(_resolve_group_type_index)(team_id, group_type)
    if group_type_index is None:
        return 0
    qs = _build_groups_queryset(team_id, group_type_index, domain_property, reenrich)
    return await sync_to_async(qs.count)()


async def enrich_organization_chunk(inputs: EnrichOrganizationChunkInputs) -> dict[str, typing.Any]:
    """Enrich one page of groups in the team via Harmonic and emit events to
    PostHog. Pure async helper with no Temporal runtime dependency so it can
    be invoked from management commands and tests in addition to the wrapping
    activity."""
    close_old_connections()
    logger = LOGGER.bind(team_id=inputs.team_id, group_type=inputs.group_type)

    from posthog.models import Group

    from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient

    capture_client = _build_capture_client()
    # Org enrichment's only event delivery path is the PostHog capture client
    # (the local `group_properties` stamp below is for dedupe within the
    # workflow). Fail loudly rather than spinning up Harmonic, paying for the
    # lookup, and then silently dropping every event while reporting
    # `enriched: N`.
    if capture_client is None:
        raise RuntimeError(
            "Cannot run organization enrichment without a capture client — "
            "set PEOPLE_ENRICHMENT_POSTHOG_API_KEY so the workflow has somewhere "
            "to write `$groupidentify` + `organization_enriched` events."
        )

    group_type_index = await sync_to_async(_resolve_group_type_index)(inputs.team_id, inputs.group_type)
    if group_type_index is None:
        logger.info("No group-type mapping for team — nothing to enrich")
        return {"processed": 0, "enriched": 0, "no_match": 0, "errors": []}

    def _load_page() -> list[_GroupRow]:
        qs = _build_groups_queryset(inputs.team_id, group_type_index, inputs.domain_property, inputs.reenrich)[
            : inputs.chunk_size
        ]
        rows: list[_GroupRow] = []
        for group in qs:
            domain = (group.group_properties or {}).get(inputs.domain_property)
            if not isinstance(domain, str) or not domain:
                continue
            rows.append(_GroupRow(pk=group.pk, group_key=group.group_key, domain=domain))
        return rows

    rows = await sync_to_async(_load_page)()
    if not rows:
        return {"processed": 0, "enriched": 0, "no_match": 0, "errors": []}

    enriched_count = 0
    no_match_count = 0
    errors: list[str] = []
    now_iso = dt.datetime.now(dt.UTC).isoformat()

    async with AsyncHarmonicClient() as harmonic:
        semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)

        async def _enrich_one(
            row: _GroupRow,
        ) -> tuple[_GroupRow, dict[str, typing.Any] | None, str | None]:
            async with semaphore:
                try:
                    data = await harmonic.enrich_company_by_domain(row.domain)
                except Exception as e:
                    return row, None, str(e)
                if data is None:
                    return row, None, None
                return row, _extract_harmonic_fields(data), None

        results = await asyncio.gather(*(_enrich_one(r) for r in rows))

    def _persist(pk: int, fields: dict[str, typing.Any] | None) -> None:
        # Local stamp serves dedupe within the workflow loop — the next chunk's
        # `_load_page` excludes groups whose `group_properties.$enriched_at` is
        # set. The canonical update still flows through `$groupidentify` below.
        group = Group.objects.get(pk=pk)
        props = group.group_properties or {}
        if fields:
            props.update({k: v for k, v in fields.items() if v is not None})
        props[ENRICHED_AT_KEY] = now_iso
        group.group_properties = props
        group.save(update_fields=["group_properties"])

    def _emit(row: _GroupRow, fields: dict[str, typing.Any]) -> None:
        non_null_fields = {k: v for k, v in fields.items() if v is not None}
        capture_client.group_identify(
            group_type=inputs.group_type,
            group_key=row.group_key,
            properties=non_null_fields,
        )
        capture_client.capture(
            distinct_id=row.group_key,
            event=ENRICHED_EVENT_NAME,
            properties={
                "enriched_fields": sorted(non_null_fields.keys()),
                "$groups": {inputs.group_type: row.group_key},
                "organization_domain": row.domain,
                **non_null_fields,
            },
        )

    for row, fields, err in results:
        if err is not None:
            errors.append(f"{row.group_key} ({row.domain}): {err}")
            # Stamp even on error so the candidate set still shrinks across
            # chunks (mirrors the people workflow's defense against persistent
            # provider errors looping the workflow forever).
            await sync_to_async(_persist)(row.pk, None)
            continue
        if fields is None:
            no_match_count += 1
            await sync_to_async(_persist)(row.pk, None)
            continue
        await sync_to_async(_persist)(row.pk, fields)
        # `_emit` issues two synchronous HTTP calls via the PostHog SDK
        # (`sync_mode=True`). Running it directly here would block the asyncio
        # event loop for ~2 round-trips per matched org; offload to a thread.
        await asyncio.to_thread(_emit, row, fields)
        enriched_count += 1

    await asyncio.to_thread(capture_client.shutdown)

    logger.info(
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
    """Bulk-enrich groups (of a customer-chosen group type) in a team via
    Harmonic. Writes the curated `$enriched_org_*` set onto the group via
    `$groupidentify` and emits an `organization_enriched` event per match.

    Pagination relies on the candidate set shrinking — every attempted group
    gets `$enriched_at` stamped in `group_properties`, so subsequent chunks
    naturally skip it. Caller controls re-runs via `reenrich=True`, which
    requires `max_chunks` to avoid an infinite loop."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> OrganizationEnrichmentInputs:
        loaded = json.loads(inputs[0])
        return OrganizationEnrichmentInputs(**loaded)

    @workflow.run
    async def run(self, inputs: OrganizationEnrichmentInputs) -> dict[str, typing.Any]:
        logger = LOGGER.bind(team_id=inputs.team_id, group_type=inputs.group_type)
        logger.info(
            "Starting organization enrichment workflow",
            chunk_size=inputs.chunk_size,
            max_chunks=inputs.max_chunks,
        )

        # Reenrich mode doesn't shrink the candidate set, so the loop would
        # otherwise run forever — mirror the people workflow's guard.
        if inputs.reenrich and inputs.max_chunks is None:
            raise ValueError("reenrich=True requires `max_chunks` to be set — otherwise the loop never terminates")

        total = await workflow.execute_activity(
            count_organizations_activity,
            args=[inputs.team_id, inputs.group_type, inputs.domain_property, inputs.reenrich],
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        estimated_chunks = math.ceil(total / inputs.chunk_size) if total else 0
        logger.info("Found enrichment targets", total=total, estimated_chunks=estimated_chunks)

        chunks_completed = 0
        totals = {"processed": 0, "enriched": 0, "no_match": 0, "errors": 0}
        sample_errors: list[str] = []

        while True:
            if inputs.max_chunks is not None and chunks_completed >= inputs.max_chunks:
                break

            result = await workflow.execute_activity(
                enrich_organization_chunk_activity,
                EnrichOrganizationChunkInputs(
                    team_id=inputs.team_id,
                    group_type=inputs.group_type,
                    domain_property=inputs.domain_property,
                    chunk_size=inputs.chunk_size,
                    reenrich=inputs.reenrich,
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

        return {
            "chunks_processed": chunks_completed,
            **totals,
            "sample_errors": sample_errors,
        }
