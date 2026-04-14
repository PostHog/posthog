"""Stripe / billing customer signals read from the duckgres Postgres DWH."""

import datetime as dt
from dataclasses import dataclass

from posthog.temporal.common.logger import get_logger

from .duckgres_client import duckgres_cursor

LOGGER = get_logger(__name__)


@dataclass
class StripeSignals:
    """Stripe + billing customer data for a single PostHog organization."""

    posthog_organization_id: str
    billing_customer_id: str
    billing_customer_name: str | None
    stripe_customer_id: str | None
    address_line_1: str | None
    address_line_2: str | None
    address_city: str | None
    address_state: str | None
    address_postal_code: str | None
    address_country: str | None
    last_changed_at: dt.datetime


# The query walks three tables, in order:
#   1. posthog_customer — link each PostHog organization to its active Stripe customer.
#   2. enriched         — join in the Stripe customer row and compute a single
#                         last_changed_at watermark as the max Fivetran sync timestamp
#                         across both sources, so an incremental run picks up either
#                         a billing_customer rename or a Stripe address update.

_FETCH_QUERY = """
WITH posthog_customer AS (
    SELECT
        cts.stripe_customer_id,
        bc.id               AS billing_customer_id,
        bc.organization_id  AS posthog_organization_id,
        bc.name             AS billing_customer_name,
        bc._fivetran_synced AS billing_customer_synced_at
    FROM ducklake.billing_public.billing_customertostripecustomer cts
    JOIN ducklake.billing_public.billing_customer bc
      ON bc.id = cts.customer_id
    WHERE cts.primary = TRUE
      AND bc.organization_id IS NOT NULL
),
enriched AS (
    SELECT
        pc.posthog_organization_id,
        pc.billing_customer_id,
        pc.billing_customer_name,
        sc.id AS stripe_customer_id,
        sc.address_line_1,
        sc.address_line_2,
        sc.address_city,
        sc.address_state,
        sc.address_postal_code,
        sc.address_country,
        GREATEST(
            COALESCE(sc._fivetran_synced,          'epoch'::timestamptz),
            COALESCE(pc.billing_customer_synced_at, 'epoch'::timestamptz)
        ) AS last_changed_at
    FROM posthog_customer pc
    LEFT JOIN ducklake.stripe.customer sc
      ON sc.id = pc.stripe_customer_id
    WHERE COALESCE(sc.is_deleted, FALSE) = FALSE
)
SELECT *
FROM enriched
WHERE %(since)s::timestamptz IS NULL
   OR last_changed_at > %(since)s::timestamptz
ORDER BY last_changed_at ASC, posthog_organization_id ASC
LIMIT %(limit)s OFFSET %(offset)s
"""


def fetch_stripe_signals(
    since: dt.datetime | None,
    limit: int,
    offset: int,
) -> list[StripeSignals]:
    """Fetch a page of stripe signals from duckgres.

    Args:
        since: Only return rows with last_changed_at strictly greater than this
            timestamp. ``None`` performs a full backfill.
        limit: Maximum rows to return in this page.
        offset: Row offset within the ordered result set.
    """
    LOGGER.info("fetching_stripe_signals", since=since.isoformat() if since else None, limit=limit, offset=offset)

    with duckgres_cursor() as cur:
        cur.execute(_FETCH_QUERY, {"since": since, "limit": limit, "offset": offset})
        rows = cur.fetchall()

    return [
        StripeSignals(
            posthog_organization_id=str(row["posthog_organization_id"]),
            billing_customer_id=str(row["billing_customer_id"]),
            billing_customer_name=row["billing_customer_name"],
            stripe_customer_id=row["stripe_customer_id"],
            address_line_1=row["address_line_1"],
            address_line_2=row["address_line_2"],
            address_city=row["address_city"],
            address_state=row["address_state"],
            address_postal_code=row["address_postal_code"],
            address_country=row["address_country"],
            last_changed_at=row["last_changed_at"],
        )
        for row in rows
    ]
