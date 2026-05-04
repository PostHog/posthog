import typing
import datetime as dt
import collections.abc
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from requests import Response

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, InstagramIntegration, Integration
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from posthog.temporal.data_imports.sources.instagram.schemas import RESOURCE_SCHEMAS, InstagramResource

from products.data_warehouse.backend.types import IncrementalFieldType

# Instagram Graph API supports up to 2 years of insights history; we cap a touch
# under that to stay safe.
INSTAGRAM_MAX_HISTORY_DAYS = 2 * 365 - 30
DEFAULT_SYNC_LOOKBACK_DAYS = 90

# How many media/story rows to fetch per page on the parent listing endpoints.
DEFAULT_PAGE_LIMIT = 100

# user_insights only supports a max 30-day window per request.
USER_INSIGHTS_MAX_DAYS_PER_REQUEST = 30


@dataclass
class InstagramResumeConfig:
    """Resume state for an Instagram sync.

    Three shapes are encoded here, distinguished by which fields are set:

    - Simple cursor pagination (``media``, ``stories``): only ``next_url`` is
      set. It is a ``paging.next`` URL with ``access_token`` stripped (see
      ``_strip_access_token``); a fresh token is re-attached at request time on
      resume.
    - Time-windowed pagination (``user_insights``): ``end_date`` acts as the
      discriminator. ``chunk_since`` describes where to restart the outer chunk
      loop. ``chunk_next_url`` is set when the crash happened mid-chunk.
    - Fan-out endpoints (``media_insights``, ``story_insights``): only
      ``parent_next_url`` is set, pointing at the next page of parents to
      iterate. We finish all child insight fetches for each parent batch before
      saving — there's no mid-parent resume in v1.

    All persisted URLs have ``access_token`` stripped.
    """

    next_url: str | None = None
    end_date: str | None = None
    chunk_since: str | None = None
    chunk_next_url: str | None = None
    parent_next_url: str | None = None


def _strip_access_token(url: str) -> str:
    """Remove the ``access_token`` query parameter from a URL.

    Meta's ``paging.next`` URLs embed the caller's access token. We never want
    that token at rest in Redis or in logs — it's re-attached at request time.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "access_token"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def _fetch_url(url: str, access_token: str, params: dict | None = None) -> Response:
    """Fetch a Graph API URL with a freshly injected access token.

    Saved URLs always have ``access_token`` stripped; the token is provided via
    ``params`` so it never persists in Redis or debug logs.
    """
    merged_params = {**(params or {}), "access_token": access_token}
    return make_tracked_session().get(url, params=merged_params)


def get_integration(config: InstagramSourceConfig, team_id: int) -> Integration:
    integration = Integration.objects.get(id=config.instagram_integration_id, team_id=team_id)
    instagram_integration = InstagramIntegration(integration)
    instagram_integration.refresh_access_token()

    if instagram_integration.integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise Exception("Failed to refresh token for Instagram integration. Please re-authorize the integration.")

    return instagram_integration.integration


def _check_response(response: Response) -> dict:
    if response.status_code != 200:
        raise Exception(f"Instagram API request failed: {response.status_code} - {response.text}")
    return response.json()


def _iter_simple_cursor(
    initial_url: str,
    initial_params: dict,
    access_token: str,
    resume_config: InstagramResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
) -> collections.abc.Generator[list[dict], None, None]:
    """Iterate a Graph API list endpoint via ``paging.next`` URLs.

    On resume, ``resume_config.next_url`` is used as the starting point and the
    initial request is skipped.
    """
    if resume_config is not None and resume_config.next_url and resume_config.end_date is None:
        response = _fetch_url(resume_config.next_url, access_token)
    else:
        response = _fetch_url(initial_url, access_token, initial_params)

    while True:
        payload = _check_response(response)
        yield payload.get("data", [])

        next_url = payload.get("paging", {}).get("next")
        if not next_url:
            return

        stripped = _strip_access_token(next_url)
        resumable_source_manager.save_state(InstagramResumeConfig(next_url=stripped))
        response = _fetch_url(stripped, access_token)


def _flatten_insights(
    raw_insights: list[dict],
    parent_id: str,
    parent_id_key: str,
    parent_timestamp: str | None,
) -> list[dict]:
    """The /insights edge returns one row per metric, each row carrying a
    ``values`` array. We flatten to one row per metric value, attaching the
    parent ID (and parent ``timestamp`` for media/stories so partitioning works).
    """
    rows: list[dict] = []
    for metric in raw_insights:
        name = metric.get("name")
        period = metric.get("period")
        title = metric.get("title")
        description = metric.get("description")
        for value in metric.get("values", []):
            row = {
                parent_id_key: parent_id,
                "name": name,
                "period": period,
                "title": title,
                "description": description,
                "value": value.get("value"),
                "end_time": value.get("end_time"),
            }
            if parent_timestamp is not None:
                row["timestamp"] = parent_timestamp
            rows.append(row)
    return rows


def _iter_fanout_insights(
    parent_url: str,
    parent_fields: list[str],
    metrics: list[str],
    parent_id_key: str,
    access_token: str,
    resume_config: InstagramResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
) -> collections.abc.Generator[list[dict], None, None]:
    """Iterate parent media/stories, then fetch /insights per parent.

    For each page of parents, yield one batch of flattened insight rows for all
    parents in that page. Resume state captures the next *parent* page URL only;
    if a crash happens mid-page the worst case is we re-fetch insights for at
    most ``DEFAULT_PAGE_LIMIT`` parents — merge dedupes on
    ``(parent_id, name)``.
    """
    if resume_config is not None and resume_config.parent_next_url:
        parent_response = _fetch_url(resume_config.parent_next_url, access_token)
    else:
        parent_response = _fetch_url(
            parent_url,
            access_token,
            {"fields": "id,timestamp", "limit": DEFAULT_PAGE_LIMIT},
        )

    while True:
        parent_payload = _check_response(parent_response)
        parents: list[dict] = parent_payload.get("data", [])

        batch: list[dict] = []
        for parent in parents:
            parent_id = parent.get("id")
            parent_timestamp = parent.get("timestamp")
            if not parent_id:
                continue
            insight_url = f"https://graph.facebook.com/{InstagramIntegration.api_version}/{parent_id}/insights"
            insight_response = _fetch_url(insight_url, access_token, {"metric": ",".join(metrics)})
            # Some media types don't support some metrics — Graph API returns 400
            # for those. Skip the parent rather than failing the whole sync.
            if insight_response.status_code == 400:
                continue
            insight_payload = _check_response(insight_response)
            batch.extend(
                _flatten_insights(
                    insight_payload.get("data", []),
                    parent_id=parent_id,
                    parent_id_key=parent_id_key,
                    parent_timestamp=parent_timestamp,
                )
            )

        if batch:
            yield batch

        next_parent_url = parent_payload.get("paging", {}).get("next")
        if not next_parent_url:
            return

        stripped = _strip_access_token(next_parent_url)
        resumable_source_manager.save_state(InstagramResumeConfig(parent_next_url=stripped))
        parent_response = _fetch_url(stripped, access_token)


def _iter_user_insights(
    base_url: str,
    metrics: list[str],
    period: str,
    ig_user_id: str,
    start_date: dt.date,
    end_date: dt.date,
    access_token: str,
    resume_config: InstagramResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
) -> collections.abc.Generator[list[dict], None, None]:
    """Iterate /me/insights in 30-day-or-smaller chunks (Graph API max).

    Resume captures ``chunk_since`` for the outer loop and ``chunk_next_url``
    for mid-chunk pagination state.
    """
    chunk_size_days = USER_INSIGHTS_MAX_DAYS_PER_REQUEST
    current_start = start_date
    pending_next_url: str | None = None

    if resume_config is not None and resume_config.end_date is not None and resume_config.chunk_since is not None:
        current_start = dt.datetime.strptime(resume_config.chunk_since, "%Y-%m-%d").date()
        pending_next_url = resume_config.chunk_next_url

    end_date_iso = end_date.strftime("%Y-%m-%d")

    def _save(since: dt.date, next_url_in_chunk: str | None) -> None:
        sanitised = _strip_access_token(next_url_in_chunk) if next_url_in_chunk else None
        resumable_source_manager.save_state(
            InstagramResumeConfig(
                end_date=end_date_iso,
                chunk_since=since.strftime("%Y-%m-%d"),
                chunk_next_url=sanitised,
            )
        )

    while current_start <= end_date:
        current_end = min(current_start + dt.timedelta(days=chunk_size_days - 1), end_date)

        if pending_next_url:
            response = _fetch_url(pending_next_url, access_token)
            pending_next_url = None
        else:
            since_ts = int(dt.datetime.combine(current_start, dt.time.min).timestamp())
            until_ts = int(dt.datetime.combine(current_end + dt.timedelta(days=1), dt.time.min).timestamp())
            response = _fetch_url(
                base_url,
                access_token,
                {
                    "metric": ",".join(metrics),
                    "period": period,
                    "since": since_ts,
                    "until": until_ts,
                },
            )

        while True:
            payload = _check_response(response)
            rows = _flatten_insights(
                payload.get("data", []),
                parent_id=ig_user_id,
                parent_id_key="ig_user_id",
                parent_timestamp=None,
            )
            if rows:
                yield rows

            next_url = payload.get("paging", {}).get("next")
            if not next_url:
                break

            stripped = _strip_access_token(next_url)
            _save(current_start, stripped)
            response = _fetch_url(stripped, access_token)

        current_start = current_end + dt.timedelta(days=1)
        _save(current_start, None)


def instagram_source(
    resource_name: str,
    config: InstagramSourceConfig,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Instagram source."""
    name = NamingConvention.normalize_identifier(resource_name)
    schema_def = RESOURCE_SCHEMAS[InstagramResource(resource_name)]

    sync_lookback_days = getattr(config, "sync_lookback_days", None)
    if sync_lookback_days is None or sync_lookback_days < 1:
        sync_lookback_days = DEFAULT_SYNC_LOOKBACK_DAYS
    sync_lookback_days = min(sync_lookback_days, INSTAGRAM_MAX_HISTORY_DAYS)

    ig_user_id = (config.ig_user_id or "").strip()

    def get_rows():
        integration = get_integration(config, team_id)
        access_token = integration.access_token
        if access_token is None:
            raise ValueError("Access token is required for Instagram integration")

        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        formatted_url = schema_def["url"].format(API_VERSION=InstagramIntegration.api_version, ig_user_id=ig_user_id)
        kind = schema_def["kind"]

        if kind == "single":
            single_params: dict[str, Any] = {"fields": ",".join(schema_def["field_names"])}
            response = _fetch_url(formatted_url, access_token, single_params)
            payload = _check_response(response)
            yield [payload]
            return

        if kind == "list":
            params: dict[str, Any] = {
                "fields": ",".join(schema_def["field_names"]),
                "limit": DEFAULT_PAGE_LIMIT,
                **schema_def["extra_params"],
            }
            yield from _iter_simple_cursor(formatted_url, params, access_token, resume_config, resumable_source_manager)
            return

        if kind in ("media_insights_fanout", "story_insights_fanout"):
            parent_id_key = "media_id" if kind == "media_insights_fanout" else "story_id"
            yield from _iter_fanout_insights(
                parent_url=formatted_url,
                parent_fields=["id", "timestamp"],
                metrics=schema_def["metrics"],
                parent_id_key=parent_id_key,
                access_token=access_token,
                resume_config=resume_config,
                resumable_source_manager=resumable_source_manager,
            )
            return

        if kind == "user_insights":
            if should_use_incremental_field and db_incremental_field_last_value is not None:
                if isinstance(db_incremental_field_last_value, dt.datetime):
                    start_date = db_incremental_field_last_value.date()
                elif isinstance(db_incremental_field_last_value, dt.date):
                    start_date = db_incremental_field_last_value
                else:
                    start_date = dt.date.today() - dt.timedelta(days=sync_lookback_days)
            else:
                start_date = dt.date.today() - dt.timedelta(days=sync_lookback_days)
            end_date = dt.date.today()
            yield from _iter_user_insights(
                base_url=formatted_url,
                metrics=schema_def["metrics"],
                period=schema_def["extra_params"].get("period", "day"),
                ig_user_id=ig_user_id,
                start_date=start_date,
                end_date=end_date,
                access_token=access_token,
                resume_config=resume_config,
                resumable_source_manager=resumable_source_manager,
            )
            return

        raise ValueError(f"Unknown Instagram resource kind: {kind}")

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=schema_def["primary_keys"],
        partition_mode=schema_def["partition_mode"],
        partition_format=schema_def["partition_format"],
        partition_keys=schema_def["partition_keys"],
    )
