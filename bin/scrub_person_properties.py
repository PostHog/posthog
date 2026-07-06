#!/usr/bin/env python3
"""Scrub person properties from every person that has them in a PostHog project.

Finds all persons carrying any of the given properties, then removes those properties.

Discovery runs one paginated JSONHas scan through the query API
(https://posthog.com/docs/api/queries), which matches a property key regardless of its
value - including null and empty values. On projects too large for that scan (the query
API rejects it with a resource-limit error), it falls back to one paginated `is_set` scan
per property through the persons API (https://posthog.com/docs/api/persons); that fallback
can miss persons whose only target properties hold null values.

Scrubbing happens either by:

  - events mode (default, fewest requests): sends `$delete_person_property` capture events
    with `$unset` through the batch endpoint - one event per person covers all matched
    properties, batched --batch-size events per request.
  - api mode: calls `POST /api/projects/:id/persons/:uuid/delete_property/` - one request
    per (person, property) pair, so prefer events mode for large scrubs.

Scrubbing is processed by the ingestion pipeline, so it is eventually consistent: persons
can keep showing the property for a short while after the script finishes.

Usage:
  export POSTHOG_PERSONAL_API_KEY=phx_...   # needs query:read and person:read (+ person:write for api mode)
  export POSTHOG_PROJECT_API_KEY=phc_...    # only needed for events mode
  python bin/scrub_person_properties.py my_secret_prop other_prop \\
      --host eu --project-id 123 --dry-run

--host accepts a full instance URL or the PostHog Cloud region shorthands us/eu.
"""

# ruff: noqa: T201 allow print statements in this CLI script

import os
import sys
import json
import time
import argparse
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests

MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0
REGION_HOSTS = {"us": "https://us.posthog.com", "eu": "https://eu.posthog.com"}


def resolve_host(value: str) -> str:
    """Map a region shorthand ('us'/'eu', any case) to its Cloud host; pass explicit hosts through."""
    return REGION_HOSTS.get(value.strip().lower(), value).rstrip("/")


class ScrubError(Exception):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr)


def request_with_retries(
    session: requests.Session, method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs: Any
) -> requests.Response:
    """Issue a request, retrying on 429 (honoring Retry-After) and 5xx with backoff."""
    last_error = ""
    for attempt in range(max_retries):
        try:
            response = session.request(method, url, timeout=60, **kwargs)
        except requests.RequestException as err:
            last_error = str(err)
            time.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", BACKOFF_BASE_SECONDS * 2**attempt))
            log(f"  rate limited, retrying in {retry_after:.0f}s...")
            time.sleep(retry_after)
            continue
        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            time.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        return response
    raise ScrubError(f"{method} {url} failed after {max_retries} attempts: {last_error}")


def run_hogql_query(
    session: requests.Session, host: str, project_id: str, query: str, max_retries: int = MAX_RETRIES
) -> list[list[Any]]:
    """Run a HogQL query through the query API and return its result rows."""
    response = request_with_retries(
        session,
        "POST",
        f"{host}/api/projects/{project_id}/query/",
        max_retries=max_retries,
        json={"query": {"kind": "HogQLQuery", "query": query}},
    )
    if response.status_code != 200:
        raise ScrubError(f"HogQL query failed (HTTP {response.status_code}): {response.text[:500]}")
    return response.json()["results"]


def hogql_string_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def iter_persons(
    session: requests.Session, host: str, project_id: str, property_filters: list[dict[str, Any]], page_size: int
) -> Iterator[dict[str, Any]]:
    """Page through the persons list API for the given property filters."""
    params = {"properties": json.dumps(property_filters), "limit": str(page_size)}
    url: Optional[str] = f"{host}/api/projects/{project_id}/persons/?{urlencode(params)}"
    page = 0
    while url:
        response = request_with_retries(session, "GET", url)
        if response.status_code != 200:
            raise ScrubError(f"Persons query failed (HTTP {response.status_code}): {response.text[:500]}")
        data = response.json()
        page += 1
        log(f"  page {page}: {len(data['results'])} persons")
        yield from data["results"]
        url = data.get("next")


def make_record(uuid: str, distinct_ids: list[str], matched: list[str]) -> dict[str, Any]:
    return {"uuid": uuid, "distinct_ids": distinct_ids, "matched_properties": matched}


def find_affected_persons_hogql(
    session: requests.Session, host: str, project_id: str, properties: list[str], page_size: int
) -> dict[str, dict[str, Any]]:
    """Find affected persons with one paginated JSONHas scan over all properties.

    JSONHas matches a key regardless of its value, so properties holding null or an empty
    string are found too - the persons API `is_set` filter misses those.
    """
    condition = " OR ".join(f"JSONHas(properties, {hogql_string_literal(p)})" for p in properties)
    log(f"Scanning persons where any of the properties exist (JSONHas): {', '.join(properties)}")
    affected: dict[str, dict[str, Any]] = {}
    # Keyset pagination on id - the query API rejects OFFSET for personal-API-key queries
    last_id: Optional[str] = None
    page = 0
    while True:
        keyset = f" AND id > toUUID({hogql_string_literal(last_id)})" if last_id else ""
        rows = run_hogql_query(
            session,
            host,
            project_id,
            f"SELECT id, properties FROM persons WHERE ({condition}){keyset} ORDER BY id ASC LIMIT {page_size}",
            # Resource-limit failures on huge projects are deterministic; fail fast to the fallback
            max_retries=2,
        )
        page += 1
        log(f"  page {page}: {len(rows)} persons")
        for row_uuid, properties_json in rows:
            if isinstance(properties_json, dict):
                person_properties = properties_json
            else:
                person_properties = json.loads(properties_json) if properties_json else {}
            matched = sorted(p for p in properties if p in person_properties)
            if matched:
                affected[str(row_uuid)] = make_record(str(row_uuid), [], matched)
        if len(rows) < page_size:
            break
        last_id = str(rows[-1][0])

    # One distinct_id per person is enough to address scrub events; fetch them in bulk
    uuids = list(affected)
    for start in range(0, len(uuids), page_size):
        chunk = uuids[start : start + page_size]
        id_list = ", ".join(f"toUUID({hogql_string_literal(u)})" for u in chunk)
        rows = run_hogql_query(
            session,
            host,
            project_id,
            f"SELECT person_id, any(distinct_id) FROM person_distinct_ids "
            f"WHERE person_id IN ({id_list}) GROUP BY person_id",
            max_retries=2,
        )
        for person_id, distinct_id in rows:
            affected[str(person_id)]["distinct_ids"] = [distinct_id]
    return affected


def find_affected_persons_api(
    session: requests.Session, host: str, project_id: str, properties: list[str], page_size: int
) -> dict[str, dict[str, Any]]:
    """Find affected persons with one paginated persons-API `is_set` scan per property.

    Persons matching several properties are deduped, and matched properties are recomputed
    from each returned person object since it carries the person's full current property set
    (so null-valued keys are scrubbed too, as long as some scan surfaced the person).
    """
    affected: dict[str, dict[str, Any]] = {}
    for prop in properties:
        log(f"Scanning persons where '{prop}' is set")
        filters = [{"key": prop, "type": "person", "operator": "is_set", "value": "is_set"}]
        for person in iter_persons(session, host, project_id, filters, page_size):
            matched = sorted(p for p in properties if p in (person.get("properties") or {}))
            if not matched:
                continue  # ClickHouse/Postgres lag - property was just unset
            record = affected.setdefault(
                person["uuid"], make_record(person["uuid"], person.get("distinct_ids") or [], [])
            )
            record["matched_properties"] = sorted(set(record["matched_properties"]) | set(matched))
    return affected


def find_affected_persons(
    session: requests.Session, host: str, project_id: str, properties: list[str], page_size: int
) -> dict[str, dict[str, Any]]:
    """Return affected persons keyed by uuid, each annotated with the target properties it has."""
    try:
        return find_affected_persons_hogql(session, host, project_id, properties, page_size)
    except ScrubError as err:
        log(f"WARNING: JSONHas scan via the query API failed: {err}")
        log(
            "Falling back to per-property is_set scans via the persons API. "
            "Persons whose only target properties hold null values may be missed."
        )
        return find_affected_persons_api(session, host, project_id, properties, page_size)


def scrub_via_events(
    host: str, project_api_key: str, affected: list[dict[str, Any]], batch_size: int
) -> tuple[int, int]:
    """Send batched $delete_person_property events with $unset. Returns (persons_scrubbed, requests_made)."""
    session = requests.Session()
    events = []
    for person in affected:
        if not person["distinct_ids"]:
            log(f"  skipping person {person['uuid']}: no distinct_ids to send an event for")
            continue
        events.append(
            {
                "event": "$delete_person_property",
                # any of the person's distinct_ids routes the event to the same merged person
                "distinct_id": person["distinct_ids"][0],
                "properties": {"$unset": person["matched_properties"]},
            }
        )

    sent = 0
    request_count = 0
    for start in range(0, len(events), batch_size):
        chunk = events[start : start + batch_size]
        response = request_with_retries(
            session, "POST", f"{host}/batch/", json={"api_key": project_api_key, "batch": chunk}
        )
        if response.status_code >= 400:
            raise ScrubError(f"Batch capture failed (HTTP {response.status_code}): {response.text[:500]}")
        sent += len(chunk)
        request_count += 1
        log(f"  sent {sent}/{len(events)} scrub events ({request_count} batch requests)")
    return sent, request_count


def scrub_via_api(
    session: requests.Session, host: str, project_id: str, affected: list[dict[str, Any]]
) -> tuple[int, list[str]]:
    """Call delete_property per (person, property). Returns (pairs_attempted, failures)."""
    failures: list[str] = []
    attempted = 0
    total_pairs = sum(len(p["matched_properties"]) for p in affected)
    for person in affected:
        for prop in person["matched_properties"]:
            url = f"{host}/api/projects/{project_id}/persons/{person['uuid']}/delete_property/"
            attempted += 1
            try:
                response = request_with_retries(session, "POST", url, json={"$unset": prop})
            except ScrubError as err:
                failures.append(f"{person['uuid']} / {prop}: {err}")
            else:
                if response.status_code >= 400:
                    failures.append(f"{person['uuid']} / {prop}: HTTP {response.status_code} {response.text[:200]}")
            if attempted % 50 == 0 or attempted == total_pairs:
                log(f"  {attempted}/{total_pairs} delete_property requests done")
    return attempted, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrub person properties from every person that has them in a PostHog project.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("properties", nargs="+", help="Person property keys to scrub")
    # Env-backed args resolve after parsing so --help never prints API keys from the environment
    parser.add_argument(
        "--host",
        default=None,
        help="PostHog instance URL, or region shorthand 'us'/'eu' for PostHog Cloud "
        "(env: POSTHOG_HOST, else https://us.posthog.com)",
    )
    parser.add_argument("--project-id", default=None, help="Numeric project ID (env: POSTHOG_PROJECT_ID)")
    parser.add_argument(
        "--personal-api-key",
        default=None,
        help="Personal API key (phx_...) for reading persons and api-mode scrubbing (env: POSTHOG_PERSONAL_API_KEY)",
    )
    parser.add_argument(
        "--project-api-key",
        default=None,
        help="Project API key (phc_...) for events-mode scrubbing (env: POSTHOG_PROJECT_API_KEY)",
    )
    parser.add_argument(
        "--mode",
        choices=["events", "api"],
        default="events",
        help="events: batched $unset capture events (1 request per --batch-size persons); "
        "api: delete_property endpoint (1 request per person-property pair)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report who would be affected; change nothing")
    parser.add_argument("--batch-size", type=int, default=500, help="Events per batch capture request (events mode)")
    parser.add_argument("--page-size", type=int, default=500, help="Persons fetched per page when scanning")
    parser.add_argument("--output", help="Write the affected persons report to this JSON file")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    args.host = resolve_host(args.host or os.environ.get("POSTHOG_HOST") or "https://us.posthog.com")
    args.project_id = args.project_id or os.environ.get("POSTHOG_PROJECT_ID")
    args.personal_api_key = args.personal_api_key or os.environ.get("POSTHOG_PERSONAL_API_KEY")
    args.project_api_key = args.project_api_key or os.environ.get("POSTHOG_PROJECT_API_KEY")
    if not args.project_id:
        parser.error("--project-id (or POSTHOG_PROJECT_ID) is required")
    if not args.personal_api_key:
        parser.error("--personal-api-key (or POSTHOG_PERSONAL_API_KEY) is required")
    if args.mode == "events" and not args.dry_run and not args.project_api_key:
        parser.error("--project-api-key (or POSTHOG_PROJECT_API_KEY) is required for events mode")
    return args


def main() -> int:
    args = parse_args()
    properties = sorted(set(args.properties))

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {args.personal_api_key}"

    log(f"Finding persons in project {args.project_id} with any of: {', '.join(properties)}")
    affected_by_uuid = find_affected_persons(session, args.host, args.project_id, properties, args.page_size)
    affected = sorted(affected_by_uuid.values(), key=lambda p: p["uuid"])

    per_property = {prop: sum(1 for p in affected if prop in p["matched_properties"]) for prop in properties}
    log("")
    log(f"Affected persons: {len(affected)}")
    for prop, count in per_property.items():
        log(f"  {prop}: {count} persons")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"properties": properties, "affected_persons": affected}, f, indent=2)
        log(f"Wrote report to {args.output}")

    if not affected:
        log("Nothing to scrub.")
        return 0

    preview = affected[:10]
    log("")
    log("Sample of affected persons:")
    for person in preview:
        distinct_id = person["distinct_ids"][0] if person["distinct_ids"] else "<no distinct_id>"
        log(f"  {person['uuid']}  {distinct_id}  -> would unset: {', '.join(person['matched_properties'])}")
    if len(affected) > len(preview):
        log(f"  ... and {len(affected) - len(preview)} more (use --output to save the full list)")

    if args.dry_run:
        log("")
        log("DRY RUN: no changes made.")
        return 0

    if not args.yes:
        pair_count = sum(len(p["matched_properties"]) for p in affected)
        prompt = (
            f"\nAbout to permanently scrub {pair_count} property values "
            f"from {len(affected)} persons via {args.mode} mode. Type 'scrub' to continue: "
        )
        if input(prompt).strip().lower() != "scrub":
            log("Aborted.")
            return 1

    if args.mode == "events":
        sent, request_count = scrub_via_events(args.host, args.project_api_key, affected, args.batch_size)
        log("")
        log(f"Done: sent {sent} scrub events in {request_count} batch requests.")
        log("Ingestion is asynchronous - properties disappear once the events are processed.")
    else:
        attempted, failures = scrub_via_api(session, args.host, args.project_id, affected)
        log("")
        log(f"Done: attempted {attempted} delete_property requests, {len(failures)} failures.")
        for failure in failures[:20]:
            log(f"  FAILED: {failure}")
        if failures:
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ScrubError as err:
        log(f"Error: {err}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("\nInterrupted.")
        sys.exit(130)
