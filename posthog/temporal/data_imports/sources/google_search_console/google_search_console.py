import time
import datetime as dt
import threading
import dataclasses
import collections.abc
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from django.conf import settings
from django.db import close_old_connections

import requests
import structlog
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials

from posthog.models.integration import Integration
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_adapter
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import GoogleSearchConsoleSourceConfig
from posthog.temporal.data_imports.sources.google_search_console.settings import SEARCH_ANALYTICS_SCHEMAS

logger = structlog.get_logger(__name__)

GSC_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"

# Two stacked Google-side limits affect Search Analytics result completeness:
#
# 1. `rowLimit` per request maxes at 25,000 (we use that here). Pagination via
#    `startRow` lets us page through more, but only up to limit (2).
# 2. There is a per-(property, date, dimension-set) cap of ~50,000 rows total
#    that Google will *ever* return, regardless of pagination. When hit, Google
#    sorts by clicks descending and silently drops the tail — no error, just a
#    truncated result.
#
# Impact by schema:
#   - by_date / by_country / by_device: tiny row counts, never sampled.
#   - by_query / by_page: typical sites unaffected; very large sites lose tail.
#   - by_query_page: cartesian over (query × page); hits the cap fastest. Top
#     50K rows by clicks are kept, the rest are dropped silently.
#
# Workarounds when sampling matters:
#   - Add a filter (e.g. country/device) to split a high-row table into smaller
#     buckets that each fit under the cap.
#   - Switch to Google's BigQuery bulk export (no row cap). Out of scope here;
#     would be a separate `_via_bigquery` source path.
#
# Separately, Google anonymizes queries from <100 unique users in a 2-3 month
# window. Those rows never appear in the API at all (but show up in chart
# totals). This is a privacy filter, independent of the 50K cap.
ROW_LIMIT = 25000

HISTORY_DAYS = 16 * 30  # Google retains ~16 months of Search Analytics data
FRESHNESS_LAG_DAYS = 3  # GSC publishes data with a 2-3 day lag

# Search Analytics is rate-limited at 1,200 QPM per site and per user, plus a
# per-second (QPS) burst cap. Paginating day-by-day across ~16 months of history
# fires requests back-to-back and trips the QPS cap, which Google reports as an
# HTTP 403 (not 429) with domain `usageLimits`. These are transient — back off
# and retry rather than failing the whole job.
# Quotas: https://developers.google.com/webmaster-tools/limits#qps-quota
QUOTA_ERROR_REASONS = frozenset({"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"})
# dailyLimitExceeded resets at midnight, so let Temporal retry the activity instead of blocking inline.
DAILY_QUOTA_REASONS = frozenset({"dailyLimitExceeded"})
QUOTA_MAX_RETRIES = 5
QUOTA_BACKOFF_BASE_SECONDS = 2.0  # exponential: ~2, 4, 8, 16, 32s — QPS windows reset within seconds

# Proactive client-side throttle to stay under the per-site QPS burst cap before
# Google rejects us. Spaces consecutive requests to the same property; the limit
# is 1,200 QPM (20 QPS) but we leave headroom for the undocumented per-second
# burst cap. Per-process only — across workers the reactive backoff above and
# Temporal's activity retry handle the remainder.
MAX_REQUESTS_PER_SECOND_PER_SITE = 5.0
_MIN_REQUEST_INTERVAL_SECONDS = 1.0 / MAX_REQUESTS_PER_SECOND_PER_SITE
_throttle_lock = threading.Lock()
_next_request_at: dict[str, float] = {}


def _throttle(site_url: str) -> None:
    """Block until this site's next request slot, spacing calls under the QPS cap."""
    with _throttle_lock:
        now = time.monotonic()
        scheduled = max(now, _next_request_at.get(site_url, 0.0))
        _next_request_at[site_url] = scheduled + _MIN_REQUEST_INTERVAL_SECONDS
        wait = scheduled - now
    if wait > 0:
        time.sleep(wait)


class GoogleSearchConsoleQuotaExceededError(Exception):
    """Raised when Search Analytics quota stays exhausted after in-line retries.

    Deliberately NOT matched by `get_non_retryable_errors` so Temporal retries
    the activity later (the resumable source picks up from the last saved date),
    which is the right recovery for the longer 10-minute / daily load quotas.
    """


@dataclasses.dataclass
class GoogleSearchConsoleResumeConfig:
    current_date: str  # ISO date currently being fetched
    start_row: int  # next startRow within current_date


def normalize_site_url(raw: str) -> str:
    """Coerce a user-entered property URL toward Google's canonical form.

    Search Console identifies a property as either ``https://example.com/`` (URL-prefix,
    trailing slash required) or ``sc-domain:example.com`` (domain). The API matches these
    strings byte-for-byte, but users routinely enter values that don't: a percent-encoded
    string copied from a URL bar (``sc-domain%3Aexample.com``), the full Search Console UI
    URL, or a URL-prefix property with the trailing slash dropped. Resolve the cases we can
    handle unambiguously and leave the rest untouched — a bare hostname (no scheme, no
    ``sc-domain:`` prefix) stays as-is because we can't tell which property type was meant.
    """
    site = raw.strip()

    # The Search Console UI URL carries the property in its `resource_id` query param.
    if site.startswith("https://search.google.com/"):
        resource_id = parse_qs(urlparse(site).query).get("resource_id")
        if resource_id:
            site = resource_id[0].strip()

    # Decode percent-encoding ('sc-domain%3A...', 'https%3A%2F%2F...%2F') copied from a URL.
    if "%" in site:
        site = unquote(site).strip()

    # URL-prefix properties are canonically stored with a trailing slash.
    if site.startswith(("http://", "https://")) and not site.endswith("/"):
        site = site + "/"

    return site


def _credentials(integration_id: int, team_id: int) -> OAuthCredentials:
    # Temporal activities run in a thread pool where Django DB connections can go
    # stale between uses (Postgres closes the connection server-side). This is
    # invoked lazily from inside `get_rows`, so the connection has often been idle
    # for minutes by the time we reach it — drop any stale connection first.
    close_old_connections()
    integration = Integration.objects.get(id=integration_id, team_id=team_id)
    return OAuthCredentials(
        token=None,
        refresh_token=integration.refresh_token,
        client_id=settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID,
        client_secret=settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        # No `scopes=` on purpose. With a refresh-token grant, google-auth forwards the
        # requested scopes to Google's token endpoint, which rejects anything that isn't an
        # exact subset of what the original consent granted — surfacing as
        # "invalid_scope: Bad Request" and failing every sync/validation. Omitting it
        # refreshes with the originally-granted scopes (matching the Google Ads client). A
        # genuinely missing scope then shows up as a 403 on the sites call, which we map to
        # an actionable "reconnect" message instead.
    )


def google_search_console_session(integration_id: int, team_id: int) -> AuthorizedSession:
    creds = _credentials(integration_id, team_id)
    session = AuthorizedSession(creds)
    adapter = make_tracked_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def list_sites(session: AuthorizedSession) -> list[dict[str, Any]]:
    response = session.get(f"{GSC_API_BASE}/sites")
    response.raise_for_status()
    return response.json().get("siteEntry", [])


def _is_quota_error(response: requests.Response) -> bool:
    """Whether a failed response is a transient rate-limit/quota error worth retrying.

    Google reports Search Analytics QPS/QPM exhaustion as a 403 with
    `error.errors[].domain == "usageLimits"` (not a 429), which is why the
    generic 403-is-fatal handling misfires. A genuine permission failure uses
    domain `global` with reason `forbidden`/`insufficientPermissions`.
    """
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    try:
        errors = response.json().get("error", {}).get("errors", [])
    except (ValueError, AttributeError, TypeError):
        return False
    return any(e.get("domain") == "usageLimits" or e.get("reason") in QUOTA_ERROR_REASONS for e in errors)


def _is_daily_quota_error(response: requests.Response) -> bool:
    if response.status_code != 403:
        return False
    try:
        errors = response.json().get("error", {}).get("errors", [])
    except (ValueError, AttributeError, TypeError):
        return False
    return any(e.get("reason") in DAILY_QUOTA_REASONS for e in errors)


def _quota_backoff_seconds(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before retrying a quota error: honor `Retry-After`, else exponential."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return QUOTA_BACKOFF_BASE_SECONDS * (2**attempt)


def _query_search_analytics(
    session: AuthorizedSession,
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    start_row: int,
    row_limit: int = ROW_LIMIT,
) -> list[dict[str, Any]]:
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "rowLimit": row_limit,
        "startRow": start_row,
        "dataState": "final",
    }
    url = f"{GSC_API_BASE}/sites/{quote(site_url, safe='')}/searchAnalytics/query"

    for attempt in range(QUOTA_MAX_RETRIES + 1):
        _throttle(site_url)
        response = session.post(url, json=body)
        if response.ok:
            return response.json().get("rows", [])

        # Surface Google's real reason (e.g. usageLimits/quotaExceeded vs forbidden) —
        # raise_for_status() discards the body where that distinction lives.
        logger.warning(
            "GSC searchAnalytics.query failed",
            site_url=site_url,
            status_code=response.status_code,
            body=response.text,
        )

        if _is_daily_quota_error(response):
            raise GoogleSearchConsoleQuotaExceededError(
                f"Search Analytics daily quota for '{site_url}' exhausted; retrying at the activity level"
            )

        if not _is_quota_error(response):
            # Permission / other errors are fatal — let the HTTPError bubble up so
            # `get_non_retryable_errors` can match "403 Client Error" / "401 Client Error".
            response.raise_for_status()

        if attempt == QUOTA_MAX_RETRIES:
            raise GoogleSearchConsoleQuotaExceededError(
                f"Search Analytics quota for '{site_url}' still exhausted after {QUOTA_MAX_RETRIES} retries"
            )

        wait = _quota_backoff_seconds(response, attempt)
        logger.warning("GSC quota exceeded, backing off", site_url=site_url, attempt=attempt, wait_seconds=wait)
        time.sleep(wait)

    # Unreachable: the loop either returns, raises for status, or raises the quota error.
    raise GoogleSearchConsoleQuotaExceededError(f"Search Analytics quota for '{site_url}' exhausted")


def _row_to_dict(row: dict[str, Any], dimensions: list[str], iter_date: dt.date | None = None) -> dict[str, Any]:
    keys = row["keys"]
    out: dict[str, Any] = {dim: keys[i] if i < len(keys) else None for i, dim in enumerate(dimensions)}
    if "date" in out and out["date"] is not None:
        out["date"] = dt.date.fromisoformat(out["date"])
    elif "date" not in out and iter_date is not None:
        # Schemas that can't include `date` in dimensions (e.g. `searchAppearance`,
        # which Google refuses to group with any other dimension) still want a per-day
        # partition in the warehouse. The iterator already calls one day at a time, so
        # any row returned belongs to that day — inject it explicitly here.
        out["date"] = iter_date
    out["clicks"] = row.get("clicks", 0)
    out["impressions"] = row.get("impressions", 0)
    out["ctr"] = row.get("ctr", 0.0)
    out["position"] = row.get("position", 0.0)
    return out


def _today() -> dt.date:
    return dt.date.today()


def _initial_start_date(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=HISTORY_DAYS)


def _resolve_window(
    today: dt.date,
    db_incremental_field_last_value: Any,
) -> tuple[dt.date, dt.date]:
    end_date = today - dt.timedelta(days=FRESHNESS_LAG_DAYS)
    if db_incremental_field_last_value is None:
        return _initial_start_date(today), end_date

    if isinstance(db_incremental_field_last_value, dt.datetime):
        last = db_incremental_field_last_value.date()
    elif isinstance(db_incremental_field_last_value, dt.date):
        last = db_incremental_field_last_value
    else:
        last = dt.date.fromisoformat(str(db_incremental_field_last_value)[:10])

    start = max(last, _initial_start_date(today))
    return start, end_date


def _iter_dates(start: dt.date, end: dt.date) -> collections.abc.Iterator[dt.date]:
    if start > end:
        return
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


def google_search_console_source(
    config: GoogleSearchConsoleSourceConfig,
    resource_name: str,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GoogleSearchConsoleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    if resource_name not in SEARCH_ANALYTICS_SCHEMAS:
        raise ValueError(f"Unknown Google Search Console schema: {resource_name}")

    schema = SEARCH_ANALYTICS_SCHEMAS[resource_name]
    dimensions = schema["dimensions"]
    primary_keys = list(schema["primary_key"])

    # Match the canonicalization done at validation time so a property that validated (e.g. a
    # percent-encoded or trailing-slash-less entry) resolves to the same string Google expects.
    site_url = normalize_site_url(config.site_url)

    name = NamingConvention.normalize_identifier(resource_name)

    def get_rows() -> collections.abc.Iterator[list[dict[str, Any]]]:
        today = _today()
        start_date, end_date = _resolve_window(
            today,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )

        resume_date: str | None = None
        resume_start_row = 0
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                resume_date = resume.current_date
                resume_start_row = resume.start_row

        session = google_search_console_session(config.google_search_console_integration_id, team_id)

        for current in _iter_dates(start_date, end_date):
            iso = current.isoformat()
            # Skip past dates already fully fetched on resume.
            if resume_date is not None and iso < resume_date:
                continue

            start_row = resume_start_row if (resume_date is not None and iso == resume_date) else 0

            while True:
                rows = _query_search_analytics(
                    session=session,
                    site_url=site_url,
                    start_date=iso,
                    end_date=iso,
                    dimensions=dimensions,
                    start_row=start_row,
                )
                if not rows:
                    break

                yield [_row_to_dict(row, dimensions, iter_date=current) for row in rows]

                next_start_row = start_row + len(rows)
                if len(rows) < ROW_LIMIT:
                    # Advance to the next date; persist its starting state so a restart
                    # picks up at the next date with start_row=0.
                    next_iso = (current + dt.timedelta(days=1)).isoformat()
                    resumable_source_manager.save_state(
                        GoogleSearchConsoleResumeConfig(current_date=next_iso, start_row=0)
                    )
                    break

                resumable_source_manager.save_state(
                    GoogleSearchConsoleResumeConfig(current_date=iso, start_row=next_start_row)
                )
                start_row = next_start_row

            # Once we've moved past the resume date, the resume offset no longer applies.
            resume_date = None
            resume_start_row = 0

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="day",
        partition_keys=["date"],
    )
