"""dlt source for Lemlist campaigns and daily per-campaign stats snapshots.

Two resources are exposed:

* ``campaigns`` — one row per campaign, upserted on ``campaign_id`` so the
  table always reflects the latest status/name/labels.
* ``campaign_stats_daily`` — one row per ``(campaign_id, snapshot_date)``
  appended every run so downstream queries can reconstruct daily deltas with
  ``LAG()``. The ``steps`` array in each stats result is left nested so dlt
  materializes it as a child table (``campaign_stats_daily__steps``) with the
  usual ``_dlt_parent_id`` back-reference.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import dlt
import requests
from dlt.sources import DltResource

LEMLIST_CAMPAIGNS_URL = "https://api.lemlist.com/api/campaigns"
LEMLIST_STATS_BATCH_URL = "https://api.lemlist.com/api/v2/campaigns/stats/batch"

DEFAULT_STATS_BATCH_SIZE = 50
_REQUEST_TIMEOUT_SECONDS = 60
LEMLIST_STATS_HISTORY_START = date(2018, 1, 1)

SessionFactory = Callable[[], requests.Session]


def _iter_campaign_pages(session: requests.Session) -> Iterator[dict[str, Any]]:
    """Yield raw campaign dicts across every page of the v2 campaigns endpoint."""
    page = 1
    while True:
        response = session.get(
            LEMLIST_CAMPAIGNS_URL,
            params={"version": "v2", "page": page},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        yield from body.get("campaigns", [])

        pagination = body.get("pagination") or {}
        next_page = pagination.get("nextPage")
        total_pages = pagination.get("totalPage", 1)
        # Lemlist sets ``nextPage`` equal to the current page on the last page,
        # so we must also guard against it not advancing to avoid an infinite loop.
        if not next_page or next_page <= page or page >= total_pages:
            break
        page = next_page


def normalize_campaign(raw: dict[str, Any]) -> dict[str, Any]:
    """Promote ``_id`` to ``campaign_id``."""
    normalized = {k: v for k, v in raw.items() if k != "_id"}
    normalized["campaign_id"] = raw.get("_id")
    return normalized


def chunk_ids(ids: list[str], size: int) -> Iterator[list[str]]:
    """Yield fixed-size chunks suitable for the batch-stats POST body."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


def build_stats_payload(campaign_ids: list[str], start_date: date, end_date: date) -> dict[str, Any]:
    """Construct the JSON body for a single batch-stats request."""
    return {
        "campaignIds": campaign_ids,
        "channels": ["email"],
        "startDate": f"{start_date.isoformat()}T00:00:00.000Z",
        "endDate": f"{end_date.isoformat()}T23:59:59.999Z",
    }


def _fetch_stats_batch(
    session: requests.Session,
    campaign_ids: list[str],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    response = session.post(
        LEMLIST_STATS_BATCH_URL,
        json=build_stats_payload(campaign_ids, start_date, end_date),
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    return list(body.get("results", []))


def build_stats_row(raw: dict[str, Any], snapshot_date: date) -> dict[str, Any]:
    """Project a single batch-stats result into a flat snapshot row."""
    row = dict(raw)
    row["campaign_id"] = row.pop("campaignId", None)
    row["snapshot_date"] = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC)
    return row


@dlt.source(name="lemlist")
def lemlist_source(
    session_factory: SessionFactory,
    snapshot_date: date,
    stats_batch_size: int = DEFAULT_STATS_BATCH_SIZE,
) -> list[DltResource]:
    """Build a dlt source that emits campaigns and a daily stats snapshot."""

    @dlt.resource(
        name="campaigns",
        primary_key="campaign_id",
        write_disposition="merge",
    )
    def campaigns() -> Iterator[dict[str, Any]]:
        with session_factory() as session:
            for raw in _iter_campaign_pages(session):
                yield normalize_campaign(raw)

    @dlt.resource(
        name="campaign_stats_daily",
        primary_key=["campaign_id", "snapshot_date"],
        write_disposition="append",
    )
    def campaign_stats_daily() -> Iterator[dict[str, Any]]:
        with session_factory() as session:
            campaign_ids = [raw["_id"] for raw in _iter_campaign_pages(session) if raw.get("_id")]
            for chunk in chunk_ids(campaign_ids, stats_batch_size):
                for raw in _fetch_stats_batch(session, chunk, LEMLIST_STATS_HISTORY_START, snapshot_date):
                    yield build_stats_row(raw, snapshot_date)

    return [campaigns, campaign_stats_daily]
