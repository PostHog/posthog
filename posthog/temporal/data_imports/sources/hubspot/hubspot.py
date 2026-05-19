"""
HubSpot resumable source for the data warehouse pipeline.

Two fetch paths:

- get_rows: paginated GET against /crm/v3/objects/{entity}. Used for full-refresh syncs
  and for the first incremental sync of a schema (before initial_sync_complete is set).
  Returns associations inline.

- get_rows_via_search: POST to /crm/v3/objects/{entity}/search with server-side date
  filtering, used for subsequent incremental syncs. Mirrors Airbyte's CRM-search
  pattern: time-windowed queries sorted by the cursor property, with cursor-advance
  sub-slicing when the 10k result cap is hit within a window. Backfills associations
  per page via v4 batch-read.
"""

import dataclasses
import urllib.parse
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.hubspot.auth import hubspot_refresh_access_token
from posthog.temporal.data_imports.sources.hubspot.helpers import BASE_URL, _get_headers, _get_property_names
from posthog.temporal.data_imports.sources.hubspot.settings import (
    ASSOCIATIONS_BATCH_SIZE,
    DEFAULT_PROPS,
    HUBSPOT_ENDPOINTS,
    OBJECT_TYPE_SINGULAR,
    SEARCH_PAGE_SIZE,
    SEARCH_RESULT_CAP,
    SEARCH_WINDOW_DAYS,
    STARTDATE,
)

PROPERTY_LENGTH_LIMIT = 16_000  # Empirically determined rough limit for the HubSpot API
# Cap on the number of properties requested via the search path. The search API has no URL-length
# concern (POST body), but each extra property multiplies backfill work and response payload size.
SEARCH_PROPERTIES_LIMIT = 250
WINDOW_SIZE_MS = SEARCH_WINDOW_DAYS * 24 * 60 * 60 * 1000


class HubspotRetryableError(Exception):
    pass


class HubspotPathologicalWindowError(Exception):
    """Raised when a single cursor-ms value has >SEARCH_RESULT_CAP records and the window
    cannot be sub-divided further. Extremely unlikely in practice for HubSpot CRM data."""


@dataclasses.dataclass
class HubspotResumeConfig:
    # Full-refresh / seed incremental (GET) path
    next_url: Optional[str] = None
    # Incremental (search) path — all three are set together
    sync_start_ms: Optional[int] = None
    sync_end_ms: Optional[int] = None
    last_cursor_ms: Optional[int] = None


def _get_properties_str(
    props: Sequence[str],
    api_key: str,
    refresh_token: str,
    object_type: str,
    logger: FilteringBoundLogger,
    include_custom_props: bool = True,
    source_id: str | None = None,
) -> str:
    """Builds a comma-separated string of properties to request from the HubSpot API (GET path)."""
    props = list(props)
    if include_custom_props:
        all_props = _get_property_names(api_key, refresh_token, object_type, source_id=source_id)
        custom_props = [prop for prop in all_props if not prop.startswith("hs_")]
        props = props + [c for c in custom_props if c not in props]

    props_str = ""
    for i, prop in enumerate(props):
        len_url_encoded_props = len(urllib.parse.quote(prop if not props_str else f"{props_str},{prop}"))
        if len_url_encoded_props > PROPERTY_LENGTH_LIMIT:
            logger.warning(
                "Your request to Hubspot is too long to process. "
                f"Therefore, only the first {i} of {len(props)} custom properties will be requested."
            )
            break
        if not props_str:
            props_str = prop
        else:
            props_str = f"{props_str},{prop}"

    return props_str


def _resolve_search_properties(
    api_key: str,
    refresh_token: str,
    endpoint: str,
    object_type: str,
    selected_properties: list[str] | None,
    include_custom_props: bool,
    required_props: Sequence[str],
    logger: FilteringBoundLogger,
    source_id: str | None,
) -> tuple[list[str], list[str]]:
    """Resolve the properties list for the search body.

    Returns (properties_list_for_request, expected_properties_for_backfill).

    `required_props` are force-included (cursor property + hs_object_id) so downstream
    code can always read the cursor and the primary key regardless of user selection.

    The returned list is capped at SEARCH_PROPERTIES_LIMIT items to bound the per-row
    backfill cost (_backfill_missing_properties is O(num_properties) per row, so a portal
    with thousands of custom properties can otherwise blow up CPU/memory at scale).
    """
    if selected_properties:
        available_props = set(_get_property_names(api_key, refresh_token, object_type, source_id=source_id))
        invalid_props = [p for p in selected_properties if p not in available_props]
        if invalid_props:
            logger.warning(
                f"HubSpot: the following selected properties do not exist for {endpoint} "
                f"and will be ignored: {invalid_props}"
            )
            selected_properties = [p for p in selected_properties if p in available_props]

        if not selected_properties:
            logger.warning(f"HubSpot: no valid selected properties for {endpoint}, falling back to defaults")
            selected_properties = None

    if selected_properties:
        props = list(selected_properties)
    else:
        props = list(DEFAULT_PROPS[endpoint])
        if include_custom_props:
            all_props = _get_property_names(api_key, refresh_token, object_type, source_id=source_id)
            custom = [p for p in all_props if not p.startswith("hs_") and p not in props]
            props.extend(custom)

    # Force-include required properties (cursor + id).
    for required in required_props:
        if required not in props:
            props.append(required)

    # Cap the properties list for search: unlike the GET path, the search POST body has no
    # URL-length pressure, but each property still multiplies the per-row backfill work and
    # the response payload. Keep the required props (they're already at the end) and truncate
    # the rest.
    if len(props) > SEARCH_PROPERTIES_LIMIT:
        required_set = set(required_props)
        non_required = [p for p in props if p not in required_set]
        required_list = [p for p in props if p in required_set]
        keep = SEARCH_PROPERTIES_LIMIT - len(required_list)
        logger.warning(
            f"HubSpot: {endpoint} has {len(props)} properties (> {SEARCH_PROPERTIES_LIMIT}); "
            f"truncating to the first {keep} non-required properties plus {len(required_list)} required."
        )
        props = non_required[:keep] + required_list

    return props, list(props)


def _build_initial_url(path: str, associations: list[str], properties: str, limit: int = 100) -> str:
    """Build the initial HubSpot API URL with query parameters."""
    parts = [f"properties={properties}", f"limit={limit}"]
    if associations:
        parts.append(f"associations={','.join(associations)}")
    return f"{BASE_URL.rstrip('/')}{path}?{'&'.join(parts)}"


def _backfill_missing_properties(row: dict[str, Any], expected_properties: list[str]) -> None:
    """HubSpot omits properties with null values; PyArrow drops absent columns during schema inference."""
    for prop in expected_properties:
        row.setdefault(prop, None)


def _flatten_result(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten a HubSpot CRM API result into a flat dict.

    Extracts properties to top level, preserves id, and flattens associations.
    """
    obj = result.get("properties", result)
    if "id" not in obj and "id" in result:
        obj["id"] = result["id"]

    if "associations" in result:
        for association in result["associations"]:
            values = [
                {
                    "value": obj.get("hs_object_id"),
                    f"{association}_id": r["id"],
                }
                for r in result["associations"][association]["results"]
            ]
            # remove duplicates from list of dicts
            values = [dict(t) for t in {tuple(d.items()) for d in values}]
            obj[association] = values

    return obj


def _iso_to_ms(value: Any) -> Optional[int]:
    """Parse a HubSpot datetime representation (ISO-8601 string, datetime, or ms int/float) to epoch ms."""
    if value is None:
        return None
    # bool is a subclass of int, so explicitly exclude it
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp() * 1000)
    if isinstance(value, str):
        # HubSpot cursor values are stringified ms in filter payloads; the same string may
        # appear on the state blob. Treat pure-digit strings as ms; otherwise parse as ISO-8601.
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        try:
            dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp() * 1000)
        except ValueError:
            return None
    return None


def get_rows(
    api_key: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubspotResumeConfig],
    include_custom_props: bool = True,
    selected_properties: list[str] | None = None,
    source_id: str | None = None,
) -> Iterator[Any]:
    """Full-refresh (and seed-incremental) fetch via the paginated GET endpoint."""
    config = HUBSPOT_ENDPOINTS[endpoint]
    object_type = OBJECT_TYPE_SINGULAR[endpoint]

    # Build properties string (called once before sync loop)
    # Keep track of the expected properties so we can backfill missing ones with None.
    # HubSpot omits properties from the response when they have no value for a record,
    # which causes PyArrow to drop those columns entirely during schema inference.
    expected_properties: list[str] | None = None

    if selected_properties:
        # Validate selected properties against what HubSpot actually has
        available_props = set(_get_property_names(api_key, refresh_token, object_type, source_id=source_id))
        invalid_props = [p for p in selected_properties if p not in available_props]
        if invalid_props:
            logger.warning(
                f"HubSpot: the following selected properties do not exist for {endpoint} "
                f"and will be ignored: {invalid_props}"
            )
            selected_properties = [p for p in selected_properties if p in available_props]

        if not selected_properties:
            logger.warning(f"HubSpot: no valid selected properties for {endpoint}, falling back to defaults")
            selected_properties = None

    if selected_properties:
        expected_properties = selected_properties
        # User explicitly selected properties — use exactly those, no custom discovery
        props_str = _get_properties_str(
            props=selected_properties,
            api_key=api_key,
            refresh_token=refresh_token,
            object_type=object_type,
            include_custom_props=False,
            logger=logger,
            source_id=source_id,
        )
    else:
        props_str = _get_properties_str(
            props=DEFAULT_PROPS[endpoint],
            api_key=api_key,
            refresh_token=refresh_token,
            object_type=object_type,
            include_custom_props=include_custom_props,
            logger=logger,
            source_id=source_id,
        )
        expected_properties = props_str.split(",") if props_str else []

    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    # Check for resume state (only use the GET-path field)
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume_config is not None and resume_config.next_url is not None:
        url = resume_config.next_url
        logger.debug(f"Hubspot: resuming from URL: {url}")
    else:
        url = _build_initial_url(
            path=config.path,
            associations=config.associations,
            properties=props_str,
        )

    @retry(
        retry=retry_if_exception_type((HubspotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict:
        nonlocal api_key, headers

        response = make_tracked_session().get(page_url, headers=headers, timeout=60)

        if response.status_code == 401:
            api_key = hubspot_refresh_access_token(refresh_token, source_id=source_id)
            headers = _get_headers(api_key)
            raise HubspotRetryableError(f"Hubspot API 401 - refreshed token, retrying: url={page_url}")

        if response.status_code == 429 or response.status_code >= 500:
            raise HubspotRetryableError(f"Hubspot API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Hubspot API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        results = data.get("results", [])
        if not results:
            break

        # Get next page URL before iterating items
        paging = data.get("paging", {})
        next_page = paging.get("next")
        next_url = next_page.get("link") if next_page else None

        for result in results:
            row = _flatten_result(result)
            if expected_properties:
                _backfill_missing_properties(row, expected_properties)
            batcher.batch(row)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

                if next_url:
                    resumable_source_manager.save_state(HubspotResumeConfig(next_url=next_url))

        if not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def _batch_read_associations(
    from_entity_plural: str,
    to_entity_plural: str,
    ids: list[str],
    headers: dict[str, str],
    refresh_token: str,
    source_id: str | None,
    logger: FilteringBoundLogger,
) -> dict[str, list[dict[str, Any]]]:
    """POST /crm/v4/associations/{from}/{to}/batch/read in chunks of ASSOCIATIONS_BATCH_SIZE.

    Returns {from_id: [{"id": to_id, "type": ...}, ...], ...} so it can be spliced into
    the GET-path `associations.{type}.results` shape that _flatten_result consumes.
    """
    if not ids:
        return {}

    url = urllib.parse.urljoin(BASE_URL, f"/crm/v4/associations/{from_entity_plural}/{to_entity_plural}/batch/read")
    by_from: dict[str, list[dict[str, Any]]] = {}

    @retry(
        retry=retry_if_exception_type((HubspotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _post_chunk(chunk_ids: list[str]) -> dict:
        nonlocal headers
        response = make_tracked_session().post(
            url,
            headers=headers,
            json={"inputs": [{"id": i} for i in chunk_ids]},
            timeout=60,
        )

        if response.status_code == 401:
            new_api_key = hubspot_refresh_access_token(refresh_token, source_id=source_id)
            headers.clear()
            headers.update(_get_headers(new_api_key))
            raise HubspotRetryableError(f"Hubspot v4 associations 401 - refreshed token, retrying: url={url}")

        if response.status_code == 429 or response.status_code >= 500:
            raise HubspotRetryableError(
                f"Hubspot v4 associations error (retryable): status={response.status_code}, url={url}"
            )

        # 404 is returned when HubSpot doesn't know about that association pair for the portal.
        # Treat as "no associations" rather than a fatal error.
        if response.status_code == 404:
            return {"results": []}

        if not response.ok:
            logger.error(
                f"Hubspot v4 associations error: status={response.status_code}, body={response.text}, url={url}"
            )
            response.raise_for_status()

        return response.json()

    for start in range(0, len(ids), ASSOCIATIONS_BATCH_SIZE):
        chunk = ids[start : start + ASSOCIATIONS_BATCH_SIZE]
        data = _post_chunk(chunk)
        for row in data.get("results", []):
            from_id = str(row.get("from", {}).get("id") or "")
            if not from_id:
                continue
            tos: list[dict[str, Any]] = []
            for to in row.get("to", []):
                to_id = to.get("toObjectId")
                if to_id is None:
                    continue
                # Match the v3 `associations[type].results[*]` shape (id + type)
                types = to.get("associationTypes") or []
                type_label = types[0].get("label") if types else None
                tos.append({"id": str(to_id), "type": type_label or ""})
            by_from[from_id] = tos

    return by_from


def _backfill_associations_into_results(
    results: list[dict[str, Any]],
    from_entity_plural: str,
    association_types: list[str],
    headers: dict[str, str],
    refresh_token: str,
    source_id: str | None,
    logger: FilteringBoundLogger,
) -> None:
    """Hydrate `result["associations"]` for each search result so _flatten_result handles it uniformly."""
    if not association_types or not results:
        return

    ids = [str(r["id"]) for r in results if "id" in r]

    for association in association_types:
        mapping = _batch_read_associations(
            from_entity_plural=from_entity_plural,
            to_entity_plural=association,
            ids=ids,
            headers=headers,
            refresh_token=refresh_token,
            source_id=source_id,
            logger=logger,
        )
        for r in results:
            tos = mapping.get(str(r.get("id", "")), [])
            r.setdefault("associations", {})
            r["associations"][association] = {"results": tos}


def get_rows_via_search(
    api_key: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubspotResumeConfig],
    db_incremental_field_last_value: Any,
    include_custom_props: bool = True,
    selected_properties: list[str] | None = None,
    source_id: str | None = None,
    now_ms: Optional[int] = None,
) -> Iterator[Any]:
    """Incremental fetch via POST /crm/v3/objects/{entity}/search.

    - Time-window the sync into SEARCH_WINDOW_DAYS-sized chunks.
    - Within each window, sort by the cursor property ASC and paginate via `after`.
    - When a sub-slice exceeds SEARCH_RESULT_CAP results, advance the lower bound to
      `sub_slice_max_cursor` (the highest cursor seen in the slice) and continue with
      GTE so boundary-cursor records are re-fetched and deduplicated by primary key,
      rather than id-walking. This avoids skipping records that share the boundary cursor.
    - Backfill associations (if any) per page via the v4 batch-read endpoint.
    - Checkpoint (sync_start_ms, sync_end_ms, last_cursor_ms) to Redis on each batch flush.
    """
    config = HUBSPOT_ENDPOINTS[endpoint]
    object_type = OBJECT_TYPE_SINGULAR[endpoint]
    cursor_prop = config.cursor_filter_property_field
    if not cursor_prop:
        raise ValueError(f"Endpoint {endpoint} does not support search-based incremental sync")

    props_list, expected_properties = _resolve_search_properties(
        api_key=api_key,
        refresh_token=refresh_token,
        endpoint=endpoint,
        object_type=object_type,
        selected_properties=selected_properties,
        include_custom_props=include_custom_props,
        required_props=[cursor_prop, "hs_object_id"],
        logger=logger,
        source_id=source_id,
    )

    headers = _get_headers(api_key)
    search_url = urllib.parse.urljoin(BASE_URL, f"{config.path}/search")
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    # Resume only from the search-path triple, not from a stray next_url left over from GET.
    if resume_config is not None and resume_config.sync_start_ms is not None and resume_config.sync_end_ms is not None:
        sync_start_ms = resume_config.sync_start_ms
        sync_end_ms = resume_config.sync_end_ms
        current_lower = resume_config.last_cursor_ms + 1 if resume_config.last_cursor_ms is not None else sync_start_ms
        logger.debug(f"Hubspot: resuming search from cursor={current_lower}ms window=[{sync_start_ms}, {sync_end_ms}]")
    else:
        seed_ms = _iso_to_ms(db_incremental_field_last_value)
        sync_start_ms = seed_ms + 1 if seed_ms is not None else _iso_to_ms(STARTDATE) or 0
        sync_end_ms = now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
        current_lower = sync_start_ms

    last_cursor_ms = current_lower

    @retry(
        retry=retry_if_exception_type((HubspotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_search(body: dict[str, Any]) -> dict:
        nonlocal api_key
        response = make_tracked_session().post(search_url, headers=headers, json=body, timeout=60)

        if response.status_code == 401:
            # Mutate `headers` in place so the shared dict stays in sync for subsequent calls
            # and for nested helpers (e.g. _batch_read_associations) that hold the same ref.
            api_key = hubspot_refresh_access_token(refresh_token, source_id=source_id)
            headers.clear()
            headers.update(_get_headers(api_key))
            raise HubspotRetryableError(f"Hubspot search 401 - refreshed token, retrying: url={search_url}")

        if response.status_code == 429 or response.status_code >= 500:
            raise HubspotRetryableError(
                f"Hubspot search error (retryable): status={response.status_code}, url={search_url}"
            )

        if not response.ok:
            logger.error(f"Hubspot search error: status={response.status_code}, body={response.text}, url={search_url}")
            response.raise_for_status()

        return response.json()

    def save_progress() -> None:
        resumable_source_manager.save_state(
            HubspotResumeConfig(
                sync_start_ms=sync_start_ms,
                sync_end_ms=sync_end_ms,
                last_cursor_ms=last_cursor_ms,
            )
        )

    while current_lower <= sync_end_ms:
        window_upper = min(current_lower + WINDOW_SIZE_MS, sync_end_ms)
        window_lower = current_lower
        after: Optional[str] = None
        window_result_count = 0
        # Per-sub-slice max cursor. Used to decide whether to advance window_lower
        # and to detect the pathological case (>=10k records sharing a single cursor value).
        sub_slice_max_cursor = window_lower - 1

        while True:
            body: dict[str, Any] = {
                "limit": SEARCH_PAGE_SIZE,
                "sorts": [{"propertyName": cursor_prop, "direction": "ASCENDING"}],
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": cursor_prop,
                                "operator": "GTE",
                                "value": str(window_lower),
                            },
                            {
                                "propertyName": cursor_prop,
                                "operator": "LTE",
                                "value": str(window_upper),
                            },
                        ]
                    }
                ],
                "properties": props_list,
            }
            if after is not None:
                body["after"] = after

            data = fetch_search(body)
            results = data.get("results", [])

            if results and config.associations:
                _backfill_associations_into_results(
                    results=results,
                    from_entity_plural=endpoint,
                    association_types=config.associations,
                    headers=headers,
                    refresh_token=refresh_token,
                    source_id=source_id,
                    logger=logger,
                )

            for result in results:
                row = _flatten_result(result)
                if expected_properties:
                    _backfill_missing_properties(row, expected_properties)

                row_cursor_ms = _iso_to_ms(row.get(cursor_prop))
                if row_cursor_ms is not None:
                    if row_cursor_ms > last_cursor_ms:
                        last_cursor_ms = row_cursor_ms
                    if row_cursor_ms > sub_slice_max_cursor:
                        sub_slice_max_cursor = row_cursor_ms

                batcher.batch(row)
                if batcher.should_yield():
                    py_table = batcher.get_table()
                    yield py_table
                    save_progress()

            window_result_count += len(results)
            paging = data.get("paging", {})
            next_cursor = paging.get("next", {}).get("after")

            # Sub-slice the window if we hit the 10k cap.
            if window_result_count >= SEARCH_RESULT_CAP:
                # If every record in this sub-slice had cursor == window_lower we can't
                # safely advance (moving to window_lower + 1 would skip any unseen records
                # at the same timestamp). This requires 10k+ records at a single ms,
                # which is effectively impossible for real HubSpot CRM data.
                if sub_slice_max_cursor <= window_lower:
                    raise HubspotPathologicalWindowError(
                        f"Hubspot search: {SEARCH_RESULT_CAP} records share cursor={window_lower}ms "
                        f"for {endpoint}; cannot sub-divide further"
                    )
                # Use GTE (not GT) so boundary records at sub_slice_max_cursor are re-fetched.
                # Primary-key dedup handles the duplicates without risk of skipping records
                # that share the boundary cursor.
                window_lower = sub_slice_max_cursor
                sub_slice_max_cursor = window_lower - 1
                after = None
                window_result_count = 0
                continue

            if not next_cursor or not results:
                break

            after = next_cursor

        # This window is drained. Advance past its upper bound.
        #   `+1` so the next window's GTE doesn't re-include the inclusive boundary record.
        current_lower = window_upper + 1
        if last_cursor_ms < window_upper:
            last_cursor_ms = window_upper
        save_progress()

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table
        save_progress()


def hubspot_source(
    api_key: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubspotResumeConfig],
    include_custom_props: bool = True,
    selected_properties: list[str] | None = None,
    source_id: str | None = None,
    db_incremental_field_last_value: Any = None,
    use_search_path: bool = False,
) -> SourceResponse:
    """Build a SourceResponse for the pipeline.

    Route selection:
    - `use_search_path=True`  → POST-search incremental path (requires initial_sync_complete
      upstream so the watermark is meaningful and associations backfill is the cheaper option).
    - `use_search_path=False` → GET path (full refresh, seed incremental, or endpoints without
      search support).
    """
    endpoint_config = HUBSPOT_ENDPOINTS[endpoint]

    if use_search_path and not endpoint_config.cursor_filter_property_field:
        raise ValueError(f"Search path requested for {endpoint} but endpoint has no cursor_filter_property_field")

    if use_search_path:
        items = lambda: get_rows_via_search(
            api_key=api_key,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
            include_custom_props=include_custom_props,
            selected_properties=selected_properties,
            source_id=source_id,
        )
    else:
        items = lambda: get_rows(
            api_key=api_key,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            include_custom_props=include_custom_props,
            selected_properties=selected_properties,
            source_id=source_id,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
