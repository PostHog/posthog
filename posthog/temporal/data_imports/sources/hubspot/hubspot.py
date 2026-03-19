"""
HubSpot resumable source for the data warehouse pipeline.

Fetches CRM objects (contacts, companies, deals, tickets, quotes, emails, meetings)
from the HubSpot API with resumable pagination support.
"""

import dataclasses
import urllib.parse
from collections.abc import Iterator, Sequence
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.hubspot.auth import hubspot_refresh_access_token
from posthog.temporal.data_imports.sources.hubspot.helpers import BASE_URL, _get_headers, _get_property_names
from posthog.temporal.data_imports.sources.hubspot.settings import (
    DEFAULT_PROPS,
    HUBSPOT_ENDPOINTS,
    OBJECT_TYPE_SINGULAR,
)

PROPERTY_LENGTH_LIMIT = 16_000  # Empirically determined rough limit for the HubSpot API


class HubspotRetryableError(Exception):
    pass


@dataclasses.dataclass
class HubspotResumeConfig:
    next_url: str


def _get_properties_str(
    props: Sequence[str],
    api_key: str,
    refresh_token: str,
    object_type: str,
    logger: FilteringBoundLogger,
    include_custom_props: bool = True,
) -> str:
    """Builds a string of properties to be requested from the HubSpot API."""
    props = list(props)
    if include_custom_props:
        all_props = _get_property_names(api_key, refresh_token, object_type)
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


def get_rows(
    api_key: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubspotResumeConfig],
    include_custom_props: bool = True,
) -> Iterator[Any]:
    config = HUBSPOT_ENDPOINTS[endpoint]
    object_type = OBJECT_TYPE_SINGULAR[endpoint]

    # Build properties string (called once before sync loop)
    props_str = _get_properties_str(
        props=DEFAULT_PROPS[endpoint],
        api_key=api_key,
        refresh_token=refresh_token,
        object_type=object_type,
        include_custom_props=include_custom_props,
        logger=logger,
    )

    # Track expected properties so we can backfill missing ones with None.
    # HubSpot omits properties from the response when they have no value for a record,
    # which causes PyArrow to drop those columns entirely during schema inference.
    expected_properties = props_str.split(",") if props_str else []

    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    # Check for resume state
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume_config is not None:
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

        response = requests.get(page_url, headers=headers, timeout=60)

        if response.status_code == 401:
            api_key = hubspot_refresh_access_token(refresh_token)
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


def hubspot_source(
    api_key: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubspotResumeConfig],
    include_custom_props: bool = True,
) -> SourceResponse:
    endpoint_config = HUBSPOT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            include_custom_props=include_custom_props,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
