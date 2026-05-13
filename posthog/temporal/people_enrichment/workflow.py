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

ENRICHMENT_TAG = "$pdl_enrichment_target"  # legacy seed-time tag, kept for backward compat
ENRICHED_AT_KEY = "$enriched_at"
ENRICHED_EVENT_NAME = "person_enriched"
DEFAULT_CHUNK_SIZE = 25
ENRICHMENT_CONCURRENCY = 5

SOURCE_PDL = "pdl"
SOURCE_CORESIGNAL = "coresignal"

FIELD_JOB_TITLE = "$enriched_job_title"
FIELD_FULL_NAME = "$enriched_full_name"
FIELD_LOCATION = "$enriched_location"
FIELD_LINKEDIN_URL = "$enriched_linkedin_url"
FIELD_PROFESSIONAL_EMAIL = "$enriched_professional_email"
FIELD_PERSONAL_EMAIL = "$enriched_personal_email"


@dataclasses.dataclass
class PeopleEnrichmentInputs:
    team_id: int
    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_chunks: int | None = None
    reenrich: bool = False  # If False, skips persons already enriched (have $pdl_enriched_at).


@dataclasses.dataclass
class EnrichChunkInputs:
    team_id: int
    offset: int
    chunk_size: int
    reenrich: bool


def _str_or_none(value: typing.Any) -> str | None:
    """PDL returns sentinel bools (``True``/``False``) for fields gated by plan tier.
    Treat anything that isn't a non-empty string as unavailable."""
    return value if isinstance(value, str) and value else None


def _extract_pdl_fields(pdl_data: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Pick the curated subset of PDL fields we store on the person."""
    personal_emails_raw = pdl_data.get("personal_emails")
    personal_email = None
    if isinstance(personal_emails_raw, list):
        for candidate in personal_emails_raw:
            personal_email = _str_or_none(candidate)
            if personal_email:
                break

    # Granular location fields (name/locality/region) are gated on most plan tiers
    # and surface as sentinel booleans; `location_country` / `location_continent`
    # remain available and act as the resilient fallback.
    location = (
        _str_or_none(pdl_data.get("location_name"))
        or _str_or_none(pdl_data.get("location_locality"))
        or _str_or_none(pdl_data.get("location_region"))
        or _str_or_none(pdl_data.get("location_country"))
        or _str_or_none(pdl_data.get("location_continent"))
    )

    return {
        FIELD_JOB_TITLE: _str_or_none(pdl_data.get("job_title")),
        FIELD_FULL_NAME: _str_or_none(pdl_data.get("full_name")),
        FIELD_LOCATION: location,
        FIELD_LINKEDIN_URL: _str_or_none(pdl_data.get("linkedin_url")),
        FIELD_PROFESSIONAL_EMAIL: _str_or_none(pdl_data.get("work_email")),
        FIELD_PERSONAL_EMAIL: personal_email,
    }


def _coresignal_active_position_title(experience: typing.Any) -> str | None:
    """Find the position_title from the entry flagged as the active experience.
    CoreSignal sets `active_experience == 1` on the current role; the top-level
    `active_experience_title` field is often null even when one exists in the
    `experience` array, so we walk it directly."""
    if not isinstance(experience, list):
        return None
    for entry in experience:
        if not isinstance(entry, dict):
            continue
        if entry.get("active_experience") == 1:
            title = _str_or_none(entry.get("position_title"))
            if title:
                return title
    return None


def _extract_coresignal_fields(cs_data: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Map CoreSignal's `employee_multi_source/collect` response into the curated set."""
    full_name = _str_or_none(cs_data.get("full_name"))
    job_title = (
        _coresignal_active_position_title(cs_data.get("experience"))
        or _str_or_none(cs_data.get("active_experience_title"))
        or _str_or_none(cs_data.get("headline"))
    )
    location = (
        _str_or_none(cs_data.get("location_full"))
        or _str_or_none(cs_data.get("location_country"))
        or _str_or_none(cs_data.get("country"))
    )
    linkedin_url = _str_or_none(cs_data.get("linkedin_url"))
    professional_email = _str_or_none(cs_data.get("primary_professional_email")) or _str_or_none(
        cs_data.get("work_email")
    )
    personal_email = _str_or_none(cs_data.get("primary_personal_email")) or _str_or_none(cs_data.get("personal_email"))

    return {
        FIELD_JOB_TITLE: job_title,
        FIELD_FULL_NAME: full_name,
        FIELD_LOCATION: location,
        FIELD_LINKEDIN_URL: linkedin_url,
        FIELD_PROFESSIONAL_EMAIL: professional_email,
        FIELD_PERSONAL_EMAIL: personal_email,
    }


_FREEMAIL_DOMAINS = {
    "gmail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "live.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}


def _company_from_email(email: str | None) -> str | None:
    """Use the email domain as a coarse company identifier for PDL's name+company
    fallback. Skips freemail providers since they don't disambiguate anything."""
    if not email or "@" not in email:
        return None
    domain = email.split("@", 1)[1].lower().strip()
    if domain in _FREEMAIL_DOMAINS:
        return None
    return domain


def _employer_brand_from_email(email: str | None) -> str | None:
    """Extract the brand portion of a corporate email's domain (the first label
    before the public suffix — `impact.com` → `impact`, `posthog.com` → `posthog`).
    CoreSignal indexes `experience.company_name` but not `company_website`, so the
    brand is what we have to match against."""
    domain = _company_from_email(email)
    if not domain:
        return None
    # Use the leftmost label as the brand; this misses some edge cases (e.g.
    # `team.acme.io` → `team`) but covers the common `acme.com` shape.
    brand = domain.split(".", 1)[0]
    return brand or None


# Local-parts that almost certainly identify a role mailbox, not a real person.
# Used to skip CoreSignal name lookups synthesized from emails like `info@…`.
_ROLE_ACCOUNT_LOCAL_PARTS = {
    "info",
    "hello",
    "hi",
    "contact",
    "support",
    "help",
    "admin",
    "team",
    "sales",
    "marketing",
    "press",
    "media",
    "billing",
    "accounts",
    "noreply",
    "no-reply",
    "office",
    "careers",
    "jobs",
}


def _name_from_email(email: str | None) -> str | None:
    """Best-effort person-name guess from an email local-part. Returns None for
    role accounts or other shapes that wouldn't make a useful search query."""
    if not email or "@" not in email:
        return None
    local_part = email.split("@", 1)[0].lower().strip()
    if not local_part or local_part in _ROLE_ACCOUNT_LOCAL_PARTS:
        return None
    # Strip trailing digits (e.g. `andy.luo7` → `andy.luo`) since they rarely
    # carry useful signal and frequently push search results off the right person.
    while local_part and local_part[-1].isdigit():
        local_part = local_part[:-1]
    if not local_part:
        return None
    # Treat `.`, `_`, `-` as word separators between first and last name.
    candidate = local_part.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    if not candidate:
        return None
    return candidate


def _enrich_one_sync(
    person_id: int,
    email: str | None,
    name: str | None,
) -> tuple[int, dict[str, typing.Any] | None, str | None, str | None]:
    """Call enrichment APIs for a single person, trying PDL first and falling back
    to CoreSignal on no-match. Returns (person_id, fields, source, error)."""
    from posthog.temporal.people_enrichment.coresignal_client import CoreSignalClient
    from posthog.temporal.people_enrichment.pdl_client import PDLClient

    pdl_data: dict[str, typing.Any] | None = None
    try:
        pdl_client = PDLClient()
        if email:
            pdl_data = pdl_client.enrich_by_email(email)
        if pdl_data is None and name:
            company = _company_from_email(email)
            if company:
                pdl_data = pdl_client.enrich_by_name_and_company(name, company)
        if pdl_data is not None:
            return person_id, _extract_pdl_fields(pdl_data), SOURCE_PDL, None
    except Exception as e:
        # If PDL itself errors, keep going to the CoreSignal fallback rather than
        # marking the whole row as failed — we still want a chance to enrich.
        LOGGER.warning("PDL lookup failed, falling back to CoreSignal", person_id=person_id, error=str(e))

    # Fallback: CoreSignal. Prefer the explicit `name` property; fall back to a
    # guess derived from the email local-part. When the email is on a non-freemail
    # domain, first try a tightened query that also requires the candidate to have
    # worked at a company whose website matches the email domain — this drastically
    # cuts same-name false positives. If that returns no hit we widen back to the
    # name-only search rather than give up.
    if not settings.CORESIGNAL_API_KEY:
        return person_id, None, None, None

    cs_search_name = name or _name_from_email(email)
    if not cs_search_name:
        return person_id, None, None, None

    employer_brand = _employer_brand_from_email(email)

    try:
        cs_client = CoreSignalClient()
        cs_data: dict[str, typing.Any] | None = None
        if employer_brand:
            # Corporate email: require the brand to appear in the candidate's active
            # employer. Do NOT fall back to broad name-only here — a same-name
            # candidate not at the expected employer is almost certainly not the
            # person we want (most observed false positives looked exactly like that).
            cs_data = cs_client.enrich_by_name_and_active_employer(cs_search_name, employer_brand)
        else:
            # Freemail / no employer signal: best we can do is the broad search.
            cs_data = cs_client.enrich_by_name(cs_search_name)
        if cs_data is None:
            return person_id, None, None, None
        return person_id, _extract_coresignal_fields(cs_data), SOURCE_CORESIGNAL, None
    except Exception as e:
        return person_id, None, None, str(e)


@activity.defn
async def count_targets_activity(team_id: int) -> int:
    """Count persons in the team tagged for PDL enrichment."""
    close_old_connections()
    from posthog.models import Person

    return await sync_to_async(Person.objects.filter(team_id=team_id, properties__has_key=ENRICHMENT_TAG).count)()


def _build_capture_client(team_id: int) -> typing.Any | None:
    """Build a PostHog Python client used to emit `person_enriched` events.

    When `PEOPLE_ENRICHMENT_POSTHOG_API_KEY` is set we route to that project
    (typically PostHog Cloud) — this is the path that actually delivers events
    and `$set` person updates end-to-end when the local ingestion pipeline isn't
    fully up. Otherwise we fall back to the local team's api token at SITE_URL.
    Returns None when neither has a usable token."""
    from posthoganalytics import Posthog

    cloud_token = settings.PEOPLE_ENRICHMENT_POSTHOG_API_KEY
    if cloud_token:
        # `sync_mode=True` flushes each call immediately, which matters here
        # because the activity finishes quickly and we don't want to rely on the
        # SDK's background thread completing before the worker reclaims it.
        return Posthog(cloud_token, host=settings.PEOPLE_ENRICHMENT_POSTHOG_HOST, sync_mode=True)

    from posthog.models import Team

    try:
        api_token = Team.objects.values_list("api_token", flat=True).get(pk=team_id)
    except Team.DoesNotExist:
        return None
    if not api_token:
        return None
    return Posthog(api_token, host=settings.SITE_URL, sync_mode=True)


async def enrich_chunk(inputs: EnrichChunkInputs) -> dict[str, typing.Any]:
    """Enrich one page of tagged persons, writing PDL fields back to `properties`.

    Pure async helper with no Temporal runtime dependency so it can be invoked
    from management commands and tests in addition to the wrapping activity.
    """
    close_old_connections()
    logger = LOGGER.bind(team_id=inputs.team_id, offset=inputs.offset)

    from posthog.models import Person

    def _load_page() -> list[tuple[int, str, str | None, str | None]]:
        qs = Person.objects.filter(team_id=inputs.team_id, properties__has_key=ENRICHMENT_TAG)
        if not inputs.reenrich:
            qs = qs.exclude(properties__has_key=ENRICHED_AT_KEY)
        # `ENRICHED_AT_KEY` is stamped on every person we attempt (match or no-match)
        # below, so the candidate set strictly shrinks across chunks. That lets us
        # pin offset to 0 and rely on filter shrinkage for progress.
        qs = qs.order_by("id")[inputs.offset : inputs.offset + inputs.chunk_size]
        rows: list[tuple[int, str, str | None, str | None]] = []
        for p in qs:
            props = p.properties or {}
            email = props.get("email") or props.get("$email")
            name = props.get("name") or props.get("$name")
            # Prefer the email as the distinct_id (also what we used when seeding);
            # fall back to the person uuid if no email is set.
            distinct_id = email or str(p.uuid)
            rows.append((p.id, distinct_id, email, name))
        return rows

    rows = await sync_to_async(_load_page)()
    if not rows:
        return {"processed": 0, "enriched": 0, "no_match": 0, "errors": []}

    capture_client = await sync_to_async(_build_capture_client)(inputs.team_id)

    semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)

    async def _run_one(
        row: tuple[int, str, str | None, str | None],
    ) -> tuple[int, str, dict[str, typing.Any] | None, str | None, str | None]:
        person_id, distinct_id, email, name = row
        async with semaphore:
            pid, fields, source, err = await asyncio.to_thread(_enrich_one_sync, person_id, email, name)
            return pid, distinct_id, fields, source, err

    results = await asyncio.gather(*(_run_one(r) for r in rows))

    enriched_count = 0
    no_match_count = 0
    errors: list[str] = []
    by_source: dict[str, int] = {}
    now_iso = dt.datetime.utcnow().isoformat() + "Z"

    def _persist(person_id: int, fields: dict[str, typing.Any] | None) -> None:
        person = Person.objects.get(pk=person_id)
        props = person.properties or {}
        if fields:
            props.update({k: v for k, v in fields.items() if v is not None})
        # Stamp every attempt (match or no-match) so the candidate set shrinks
        # and subsequent runs don't retry the same persons indefinitely.
        props[ENRICHED_AT_KEY] = now_iso
        person.properties = props
        person.save(update_fields=["properties"])

    def _capture_event(distinct_id: str, fields: dict[str, typing.Any]) -> None:
        if not capture_client:
            return
        non_null_fields = {k: v for k, v in fields.items() if v is not None}
        # Two calls intentionally:
        #   1. `capture` emits the `person_enriched` event with the enriched fields
        #      flattened on the event so they show up in events queries.
        #   2. `set` sends a dedicated `$set` event so the ingestion pipeline
        #      updates `person.properties` with the same fields. Nesting `$set`
        #      inside `capture` properties does *not* drive person updates for
        #      custom events in the PostHog Python SDK; the canonical path is the
        #      dedicated `posthog.set` method.
        capture_client.capture(
            distinct_id=distinct_id,
            event=ENRICHED_EVENT_NAME,
            properties={
                "enriched_fields": sorted(non_null_fields.keys()),
                **non_null_fields,
            },
        )
        capture_client.set(distinct_id=distinct_id, properties=non_null_fields)

    for person_id, distinct_id, fields, source, err in results:
        if err is not None:
            errors.append(f"person {person_id}: {err}")
            continue
        if fields is None:
            no_match_count += 1
            await sync_to_async(_persist)(person_id, None)
            continue
        await sync_to_async(_persist)(person_id, fields)
        await sync_to_async(_capture_event)(distinct_id, fields)
        if source:
            # `source` is kept for the workflow's `by_source` rollup metric and
            # the activity log line only — it isn't persisted on the person or
            # surfaced in the event payload.
            by_source[source] = by_source.get(source, 0) + 1
        enriched_count += 1

    if capture_client is not None:
        # Flush queued events before we return so a worker shutdown doesn't lose them.
        await asyncio.to_thread(capture_client.shutdown)

    logger.info(
        "Enriched chunk",
        processed=len(rows),
        enriched=enriched_count,
        no_match=no_match_count,
        errors=len(errors),
        by_source=by_source,
    )

    return {
        "processed": len(rows),
        "enriched": enriched_count,
        "no_match": no_match_count,
        "errors": errors,
        "by_source": by_source,
    }


@activity.defn
async def enrich_people_chunk_activity(inputs: EnrichChunkInputs) -> dict[str, typing.Any]:
    async with Heartbeater():
        return await enrich_chunk(inputs)


@workflow.defn(name="people-enrichment-pdl")
class PeopleEnrichmentWorkflow(PostHogWorkflow):
    """Bulk-enrich tagged persons via the People Data Labs API."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PeopleEnrichmentInputs:
        loaded = json.loads(inputs[0])
        return PeopleEnrichmentInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PeopleEnrichmentInputs) -> dict[str, typing.Any]:
        logger = LOGGER.bind(team_id=inputs.team_id)
        logger.info("Starting people enrichment workflow", chunk_size=inputs.chunk_size)

        total = await workflow.execute_activity(
            count_targets_activity,
            inputs.team_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        estimated_chunks = math.ceil(total / inputs.chunk_size) if total else 0
        logger.info("Found enrichment targets", total=total, estimated_chunks=estimated_chunks)

        offset = 0
        chunk_number = 0
        totals = {"processed": 0, "enriched": 0, "no_match": 0, "errors": 0}
        by_source: dict[str, int] = {}
        sample_errors: list[str] = []

        while True:
            if inputs.max_chunks is not None and chunk_number >= inputs.max_chunks:
                break

            result = await workflow.execute_activity(
                enrich_people_chunk_activity,
                EnrichChunkInputs(
                    team_id=inputs.team_id,
                    offset=offset,
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

            for source, count in (result.get("by_source") or {}).items():
                by_source[source] = by_source.get(source, 0) + count

            if processed < inputs.chunk_size:
                break

            # offset stays pinned at 0 — candidate set shrinks via ENRICHED_AT_KEY stamping
            chunk_number += 1

        return {
            "team_id": inputs.team_id,
            "chunks_processed": chunk_number + 1,
            **totals,
            "by_source": by_source,
            "sample_errors": sample_errors,
        }
