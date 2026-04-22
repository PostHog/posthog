"""dlt source for Lemlist campaigns and daily per-campaign stats snapshots.

Two resources are exposed:

* ``campaigns`` — one row per campaign, upserted on ``campaign_id`` so the
  table always reflects the latest status/name/labels.
* ``campaign_stats_daily`` — one row per ``(campaign_id, snapshot_date)``,
  appended every run. Ducklake rejects the DDL dlt emits for ``merge``
  dispositions (``ALTER TABLE … ADD COLUMN … NOT NULL``), so per-day
  idempotency is handled by the Dagster asset: it deletes any prior rows for
  the current ``snapshot_date`` before each run. Downstream queries
  reconstruct daily deltas with ``LAG()``. The ``steps`` array in each stats
  result is left nested so dlt materializes it as a child table
  (``campaign_stats_daily__steps``) with the usual ``_dlt_parent_id``
  back-reference.
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


class LemlistPartialBatchError(RuntimeError):
    """Raised when Lemlist's batch stats endpoint returns an incomplete response."""


def _iter_campaign_pages(session: requests.Session) -> Iterator[dict[str, Any]]:
    """Yield raw campaign dicts across every page of the v2 campaigns endpoint."""
    page: int = 1
    while True:
        response = session.get(
            LEMLIST_CAMPAIGNS_URL,
            params={"version": "v2", "page": str(page)},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        yield from body.get("campaigns", [])

        pagination = body.get("pagination") or {}
        next_page = pagination.get("nextPage")
        total_pages = pagination.get("totalPage")
        # Lemlist sets ``nextPage`` equal to the current page on the last page,
        # so we must also guard against it not advancing to avoid an infinite loop.
        if not next_page or next_page <= page:
            break
        if total_pages is not None and page >= total_pages:
            break
        page = next_page


def normalize_campaign(raw: dict[str, Any]) -> dict[str, Any]:
    """Promote ``_id`` to ``campaign_id``."""
    normalized = {k: v for k, v in raw.items() if k != "_id"}
    normalized["campaign_id"] = raw["_id"]
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
    results = list(body.get("results", []))
    errors = list(body.get("errors") or [])

    if errors:
        raise LemlistPartialBatchError(
            f"Lemlist batch stats returned {len(errors)} error(s) for "
            f"{len(campaign_ids)} requested campaign(s): {errors!r}"
        )

    returned_ids = {row.get("campaignId") for row in results}
    missing_ids = [cid for cid in campaign_ids if cid not in returned_ids]
    if missing_ids:
        raise LemlistPartialBatchError(
            f"Lemlist batch stats returned {len(results)} result(s) for "
            f"{len(campaign_ids)} requested campaign(s); missing: {missing_ids!r}"
        )

    return results


def build_stats_row(raw: dict[str, Any], snapshot_date: date) -> dict[str, Any]:
    """Project a single batch-stats result into a flat snapshot row."""
    row = dict(raw)
    row["campaign_id"] = row.pop("campaignId")
    row["snapshot_date"] = datetime(snapshot_date.year, snapshot_date.month, snapshot_date.day, tzinfo=UTC)
    return row


@dlt.source(name="lemlist")
def lemlist_source(
    session_factory: SessionFactory,
    snapshot_date: date,
    stats_batch_size: int = DEFAULT_STATS_BATCH_SIZE,
) -> list[DltResource]:
    """Build a dlt source that emits campaigns and a daily stats snapshot."""
    raw_campaigns_cache: list[dict[str, Any]] | None = None

    def load_raw_campaigns() -> list[dict[str, Any]]:
        nonlocal raw_campaigns_cache
        if raw_campaigns_cache is None:
            with session_factory() as session:
                raw_campaigns_cache = list(_iter_campaign_pages(session))
        return raw_campaigns_cache

    @dlt.resource(
        name="campaigns",
        primary_key="campaign_id",
        write_disposition="merge",
    )
    def campaigns() -> Iterator[dict[str, Any]]:
        for raw in load_raw_campaigns():
            yield normalize_campaign(raw)

    # The logical key is ``(campaign_id, snapshot_date)``, but we deliberately
    # omit ``primary_key`` here: dlt would translate it into ``NOT NULL`` /
    # ``UNIQUE`` column constraints, and Ducklake rejects
    # ``ALTER TABLE … ADD COLUMN … <constraint>`` DDL when the schema evolves.
    # Per-day idempotency is enforced by the Dagster asset's pre-delete.
    @dlt.resource(
        name="campaign_stats_daily",
        write_disposition="append",
    )
    def campaign_stats_daily() -> Iterator[dict[str, Any]]:
        campaign_ids = [raw["_id"] for raw in load_raw_campaigns()]
        if not campaign_ids:
            return
        with session_factory() as session:
            for chunk in chunk_ids(campaign_ids, stats_batch_size):
                for raw in _fetch_stats_batch(session, chunk, LEMLIST_STATS_HISTORY_START, snapshot_date):
                    yield build_stats_row(raw, snapshot_date)

    return [campaigns, campaign_stats_daily]
