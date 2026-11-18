"""Hosting region of PostHog organizations, read from billing licenses in the duckgres DWH."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from itertools import batched

from psycopg import sql

from .constants import ORG_REGION_BY_LICENSE_ID
from .duckgres_client import duckgres_cursor

_LOOKUP_CHUNK_SIZE = 1_000
_STATEMENT_TIMEOUT_MS = 60 * 1000

# Each ID gets its own scalar placeholder, because duckgres accepts scalar binds
# (the Stripe query uses them) while array binds are unverified. The ID is read
# back as text, so the rows hold strings whatever the column type is.
_FETCH_QUERY = sql.SQL(
    "SELECT CAST(organization_id AS VARCHAR) AS organization_id, license_id "
    "FROM ducklake.billing_public.billing_customer "
    "WHERE CAST(organization_id AS VARCHAR) IN ({placeholders})"
)


def normalize_org_id(org_id: str | None) -> str:
    return (org_id or "").strip().lower()


def _is_canonical_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def fetch_org_regions(org_ids: Iterable[str]) -> dict[str, str]:
    """Map organization IDs, normalized, to "US" or "EU" by their billing license.

    An organization gets no entry when it has no billing customer, when its license
    names no region, or when its customers name different regions. A missing region
    is never defaulted.
    """
    # A Salesforce stamp that is not a canonical UUID cannot match a billing customer.
    # Leaving it out keeps one malformed stamp from failing a query and costing the
    # whole page its regions.
    lookup_ids = sorted({org_id for org_id in map(normalize_org_id, org_ids) if _is_canonical_uuid(org_id)})
    if not lookup_ids:
        return {}

    regions_found: dict[str, set[str | None]] = defaultdict(set)
    with duckgres_cursor() as cur:
        cur.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(_STATEMENT_TIMEOUT_MS)))
        for chunk in batched(lookup_ids, _LOOKUP_CHUNK_SIZE, strict=False):
            placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(chunk))
            cur.execute(_FETCH_QUERY.format(placeholders=placeholders), list(chunk))
            for row in cur.fetchall():
                region = ORG_REGION_BY_LICENSE_ID.get(row["license_id"])
                regions_found[normalize_org_id(row["organization_id"])].add(region)

    regions: dict[str, str] = {}
    for org_id, found in regions_found.items():
        region = next(iter(found)) if len(found) == 1 else None
        if region is not None:
            regions[org_id] = region
    return regions
