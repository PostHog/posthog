import json
import typing
import datetime as dt
import collections.abc
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from requests import Response

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, MetaAdsIntegration
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat, PartitionMode, SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import MetaAdsSourceConfig
from posthog.temporal.data_imports.sources.meta_ads.schemas import RESOURCE_SCHEMAS

from products.data_warehouse.backend.types import IncrementalFieldType

# Meta Ads API only supports data from the last 3 years
META_ADS_MAX_HISTORY_DAYS = 3 * 365
DEFAULT_SYNC_LOOKBACK_DAYS = 90


@dataclass
class MetaAdsResumeConfig:
    """Resume state for a Meta Ads sync.

    Two shapes are encoded here:

    - Simple pagination (non-stats endpoints, no time range): only ``next_url``
      is set. It is a ``paging.next`` URL returned by the Graph API with its
      ``access_token`` query param stripped (see ``_strip_access_token``); the
      token is re-attached from the integration config at request time on
      resume.
    - Time-range pagination (stats endpoints): ``end_date`` acts as the
      discriminator. ``chunk_since`` and ``chunk_size_days`` describe where to
      restart the outer chunk loop. ``chunk_next_url`` is set when the crash
      happened mid-chunk — on resume we fetch that URL directly, skipping the
      initial chunk request. When the chunk was complete at save time,
      ``chunk_next_url`` is None and we issue a fresh initial request for
      ``chunk_since``. Saved URLs have ``access_token`` stripped.
    """

    next_url: str | None = None
    end_date: str | None = None
    chunk_since: str | None = None
    chunk_size_days: int | None = None
    chunk_next_url: str | None = None


def _strip_access_token(url: str) -> str:
    """Remove the ``access_token`` query parameter from a URL.

    Meta's ``paging.next`` URLs embed the caller's access token as a query
    param. We never want that token at rest in Redis or in logs — we re-attach
    a fresh one from the integration config at request time.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "access_token"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def _fetch_paging_url(url: str, access_token: str) -> Response:
    """Fetch a Meta ``paging.next``-style URL with a freshly injected access token.

    Saved URLs have ``access_token`` stripped; we pass it via ``params`` at
    request time so the token never persists in Redis or debug logs.
    """
    return make_tracked_session().get(url, params={"access_token": access_token})


def _clean_account_id(s: str | None) -> str | None:
    """Clean account IDs from Meta Ads.
    Account IDs should have 'act_' prefix for API calls.
    """
    if not s:
        return s

    s = s.strip()
    if not s.startswith("act_"):
        s = f"act_{s}"
    return s


def get_integration(config: MetaAdsSourceConfig, team_id: int) -> Integration:
    """Get the Meta Ads integration."""
    integration = Integration.objects.get(id=config.meta_ads_integration_id, team_id=team_id)
    meta_ads_integration = MetaAdsIntegration(integration)
    meta_ads_integration.refresh_access_token()

    if meta_ads_integration.integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise Exception("Failed to refresh token for Meta Ads integration. Please re-authorize the integration.")

    return meta_ads_integration.integration


@dataclass
class MetaAdsSchema:
    name: str
    primary_keys: list[str]
    field_names: list[str]
    url: str
    extra_params: dict
    partition_keys: list[str]
    partition_mode: PartitionMode
    partition_format: PartitionFormat
    is_stats: bool


# Note: can make this static but keeping schemas.py to match other schema files for now
def get_schemas() -> dict[str, MetaAdsSchema]:
    """Obtain Meta Ads schemas using predefined field definitions."""
    schemas: dict[str, MetaAdsSchema] = {}

    for resource_name, schema_def in RESOURCE_SCHEMAS.items():
        field_names = schema_def["field_names"].copy()
        primary_keys = schema_def["primary_keys"]
        url = schema_def["url"]
        extra_params = schema_def["extra_params"]
        partition_keys = schema_def["partition_keys"]
        partition_mode = schema_def["partition_mode"]
        partition_format = schema_def["partition_format"]
        is_stats = schema_def.get("is_stats", False)

        schema = MetaAdsSchema(
            name=resource_name,
            primary_keys=primary_keys,
            field_names=field_names,
            url=url,
            extra_params=extra_params,
            partition_keys=partition_keys,
            partition_mode=partition_mode,
            partition_format=partition_format,
            is_stats=is_stats,
        )

        schemas[resource_name] = schema

    return schemas


# Error subcodes indicating the request timed out due to too much data
# https://developers.facebook.com/docs/marketing-api/insights/error-codes
META_TIMEOUT_ERROR_SUBCODES = {1504018, 1504038}

# Chunk sizes for adaptive time-range pagination (in days)
# Start with 30-day chunks, fall back to smaller chunks on timeout
TIME_RANGE_CHUNK_SIZES = [30, 7, 1]


def _is_timeout_error(response: Response) -> bool:
    """Check if the response is a Meta API timeout error that can be resolved with smaller date ranges."""
    try:
        error = response.json().get("error", {})

        if error.get("error_subcode") in META_TIMEOUT_ERROR_SUBCODES:
            return True

        # This check is a bit fragile, but the Meta API has been observed to return a 500 response like this:
        # {"error":{"code":1,"message":"Please reduce the amount of data you're asking for, then retry your request"}}
        message = str(error.get("message") or "").lower()
        return error.get("code") == 1 and "reduce the amount of data" in message
    except (ValueError, KeyError, AttributeError):
        return False


def _iter_simple_pagination(
    initial_url: str,
    params: dict,
    resume_config: MetaAdsResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
) -> collections.abc.Generator[list[dict], None, None]:
    """Iterate a non-time-range Graph API request via ``paging.next`` URLs.

    On resume, the saved ``next_url`` is re-issued with a fresh ``access_token``
    injected at request time, so the initial request is skipped.
    """
    access_token = params["access_token"]
    if resume_config is not None and resume_config.next_url and resume_config.end_date is None:
        response = _fetch_paging_url(resume_config.next_url, access_token)
    else:
        response = make_tracked_session().get(initial_url, params=params)

    while True:
        if response.status_code != 200:
            raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

        response_payload = response.json()
        yield response_payload.get("data", [])

        next_url = response_payload.get("paging", {}).get("next")
        if not next_url:
            return

        # Saved state points at the NEXT page. On resume we re-fetch from there;
        # the already-yielded page is not re-emitted (primary keys would dedupe it anyway).
        # Strip access_token from the URL before using it so we don't end up with a
        # duplicated `access_token` query param (requests merges `params=...` into the URL).
        stripped_next_url = _strip_access_token(next_url)
        resumable_source_manager.save_state(MetaAdsResumeConfig(next_url=stripped_next_url))
        response = _fetch_paging_url(stripped_next_url, access_token)


def _iter_time_range_pagination(
    url: str,
    params: dict,
    time_range: dict,
    resume_config: MetaAdsResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
) -> collections.abc.Generator[list[dict], None, None]:
    """Iterate an insights-style request by chunked date ranges.

    The outer loop walks adaptive date chunks (30/7/1 days). The inner loop
    follows ``paging.next`` within each chunk. Resume state captures both
    levels: ``chunk_since`` + ``chunk_size_days`` for the outer loop, and
    ``chunk_next_url`` when the crash happened mid-chunk.
    """
    access_token = params["access_token"]
    start_date = dt.datetime.strptime(time_range["since"], "%Y-%m-%d")
    end_date = dt.datetime.strptime(time_range["until"], "%Y-%m-%d")

    chunk_size_days = TIME_RANGE_CHUNK_SIZES[0]
    current_start = start_date
    pending_next_url: str | None = None

    if resume_config is not None and resume_config.end_date is not None and resume_config.chunk_since is not None:
        current_start = dt.datetime.strptime(resume_config.chunk_since, "%Y-%m-%d")
        chunk_size_days = resume_config.chunk_size_days or TIME_RANGE_CHUNK_SIZES[0]
        pending_next_url = resume_config.chunk_next_url

    end_date_iso = end_date.strftime("%Y-%m-%d")

    def _save(since: dt.datetime, size_days: int, next_url_in_chunk: str | None) -> None:
        # Saved URLs have the access_token stripped so the token never sits
        # at rest in Redis or appears in debug logs.
        sanitised = _strip_access_token(next_url_in_chunk) if next_url_in_chunk else None
        resumable_source_manager.save_state(
            MetaAdsResumeConfig(
                end_date=end_date_iso,
                chunk_since=since.strftime("%Y-%m-%d"),
                chunk_size_days=size_days,
                chunk_next_url=sanitised,
            )
        )

    while current_start <= end_date:
        current_end = min(current_start + dt.timedelta(days=chunk_size_days - 1), end_date)

        if pending_next_url:
            # Mid-chunk resume: re-attach a fresh access_token at request time.
            response = _fetch_paging_url(pending_next_url, access_token)
            pending_next_url = None
        else:
            chunk_time_range = {
                "since": current_start.strftime("%Y-%m-%d"),
                "until": current_end.strftime("%Y-%m-%d"),
            }
            chunk_params = {**params, "time_range": json.dumps(chunk_time_range)}
            response = make_tracked_session().get(url, params=chunk_params)

            if response.status_code != 200:
                # Fallback only happens on the initial chunk request (before any data is yielded).
                if _is_timeout_error(response) and chunk_size_days in TIME_RANGE_CHUNK_SIZES:
                    current_index = TIME_RANGE_CHUNK_SIZES.index(chunk_size_days)
                    if current_index < len(TIME_RANGE_CHUNK_SIZES) - 1:
                        chunk_size_days = TIME_RANGE_CHUNK_SIZES[current_index + 1]
                        continue
                raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

        while True:
            if response.status_code != 200:
                raise Exception(f"Meta API request failed: {response.status_code} - {response.text}")

            response_payload = response.json()
            yield response_payload.get("data", [])

            next_url = response_payload.get("paging", {}).get("next")
            if not next_url:
                break

            # Strip the token once and use the same URL for both save and fetch,
            # otherwise `requests.get(url_with_token, params={access_token: ...})`
            # would send two `access_token` query params.
            stripped_next_url = _strip_access_token(next_url)
            _save(current_start, chunk_size_days, stripped_next_url)
            response = _fetch_paging_url(stripped_next_url, access_token)

        current_start = current_end + dt.timedelta(days=1)
        # Always save the chunk-boundary state, even when we've advanced past
        # end_date. This clears any stale mid-chunk next_url from the previous
        # iteration (so a resume doesn't redo already-completed pagination)
        # and guarantees a crash right after the final chunk finds the loop
        # already satisfied on restart.
        _save(current_start, chunk_size_days, None)


def _make_paginated_api_request(
    url: str,
    params: dict,
    access_token: str,
    time_range: dict | None,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
) -> collections.abc.Generator[list[dict], None, None]:
    """Make paginated requests to the Meta Graph API.
    This function handles two types of pagination:
    1. Standard pagination: Uses Meta's paging.next URLs to fetch all pages of results
    2. Time-range pagination: Breaks large date ranges into chunks, with adaptive fallback
       to smaller chunks (30-day -> 7-day -> 1-day) if the API times out
    """
    params = {**params, "access_token": access_token}
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if time_range is None:
        yield from _iter_simple_pagination(url, params, resume_config, resumable_source_manager)
    else:
        yield from _iter_time_range_pagination(url, params, time_range, resume_config, resumable_source_manager)


def meta_ads_source(
    resource_name: str,
    config: MetaAdsSourceConfig,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Meta Ads source."""
    name = NamingConvention.normalize_identifier(resource_name)
    schema = get_schemas()[resource_name]

    sync_lookback_days = getattr(config, "sync_lookback_days", None)
    if sync_lookback_days is None or sync_lookback_days < 1:
        sync_lookback_days = DEFAULT_SYNC_LOOKBACK_DAYS
    sync_lookback_days = min(sync_lookback_days, META_ADS_MAX_HISTORY_DAYS)

    def get_rows():
        integration = get_integration(config, team_id)
        access_token = integration.access_token

        if access_token is None:
            raise ValueError("Access token is required for Meta Ads integration")

        # Determine date range for incremental sync
        time_range = None

        if should_use_incremental_field:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: dt.date = dt.date.today() - dt.timedelta(days=sync_lookback_days)
            else:
                last_value = db_incremental_field_last_value

            start_date = last_value.strftime("%Y-%m-%d")
            # Meta Ads API is day based so only import if the day is complete
            end_date = dt.date.today().strftime("%Y-%m-%d")
            time_range = {
                "since": start_date,
                "until": end_date,
            }
        elif schema.is_stats:
            time_range = {
                "since": (dt.date.today() - dt.timedelta(days=sync_lookback_days)).strftime("%Y-%m-%d"),
                "until": dt.date.today().strftime("%Y-%m-%d"),
            }

        formatted_url = schema.url.format(
            API_VERSION=MetaAdsIntegration.api_version, account_id=_clean_account_id(config.account_id)
        )
        params = {
            "fields": ",".join(schema.field_names),
            "limit": 500,
            **schema.extra_params,
        }

        yield from _make_paginated_api_request(
            formatted_url, params, access_token, time_range, resumable_source_manager
        )

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=schema.primary_keys,
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_keys=schema.partition_keys,
    )
