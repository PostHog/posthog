import datetime as dt
import dataclasses
import collections.abc
from typing import Any
from urllib.parse import quote

from django.conf import settings

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials

from posthog.models.integration import Integration
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_adapter
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import GoogleSearchConsoleSourceConfig
from posthog.temporal.data_imports.sources.google_search_console.settings import SEARCH_ANALYTICS_SCHEMAS

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


@dataclasses.dataclass
class GoogleSearchConsoleResumeConfig:
    current_date: str  # ISO date currently being fetched
    start_row: int  # next startRow within current_date


def _credentials(integration_id: int, team_id: int) -> OAuthCredentials:
    integration = Integration.objects.get(id=integration_id, team_id=team_id)
    return OAuthCredentials(
        token=None,
        refresh_token=integration.refresh_token,
        client_id=settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID,
        client_secret=settings.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
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
    response = session.post(
        f"{GSC_API_BASE}/sites/{quote(site_url, safe='')}/searchAnalytics/query",
        json=body,
    )
    response.raise_for_status()
    return response.json().get("rows", [])


def _row_to_dict(row: dict[str, Any], dimensions: list[str]) -> dict[str, Any]:
    keys = row.get("keys", [])
    out: dict[str, Any] = {dim: keys[i] if i < len(keys) else None for i, dim in enumerate(dimensions)}
    if "date" in out and out["date"] is not None:
        out["date"] = dt.date.fromisoformat(out["date"])
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
                    site_url=config.site_url,
                    start_date=iso,
                    end_date=iso,
                    dimensions=dimensions,
                    start_row=start_row,
                )
                if not rows:
                    break

                yield [_row_to_dict(row, dimensions) for row in rows]

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
