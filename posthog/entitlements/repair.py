import json

from django.db import connections

from posthog.dataclasses import frozen
from posthog.entitlements.registry import get_entitlement_reactor_registry

CANDIDATE_PAGE_SIZE = 200

# Each indexed source page is bounded before expansion, including pages with no behind rows.
BEHIND_PAGE_SQL = """
WITH candidates AS MATERIALIZED (
    SELECT id, available_product_features
    FROM posthog_organization
    WHERE id > %s::uuid
    ORDER BY id
    LIMIT %s
), reactors AS (
    SELECT * FROM jsonb_to_recordset(%s::jsonb) AS r(key text, feature_keys jsonb)
), behind AS (
    SELECT o.id FROM candidates o
    WHERE jsonb_array_length(COALESCE(to_jsonb(o.available_product_features), '[]'::jsonb)) > 0
    AND EXISTS (
        SELECT 1 FROM reactors r
        JOIN posthog_organizationentitlementappliedstate a
            ON a.organization_id = o.id AND a.reactor_key = r.key
        WHERE (
            SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'key', f->'key', 'limit', f->'limit', 'unit', f->'unit'
            ) ORDER BY (f->>'key') COLLATE "C"), '[]'::jsonb)
            FROM jsonb_array_elements(to_jsonb(o.available_product_features)) f
            WHERE r.feature_keys ? (f->>'key')
        ) IS DISTINCT FROM (
            SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'key', f->'key', 'limit', f->'limit', 'unit', f->'unit'
            ) ORDER BY (f->>'key') COLLATE "C"), '[]'::jsonb)
            FROM jsonb_array_elements(a.snapshot) f
        )
    )
)
SELECT COALESCE((SELECT jsonb_agg(id ORDER BY id) FROM behind), '[]'::jsonb),
       (SELECT id::text FROM candidates ORDER BY id DESC LIMIT 1),
       (SELECT count(*) FROM candidates)
"""


@frozen
class BehindOrganizationsPage:
    organization_ids: list[str]
    cursor: str | None
    candidate_count: int


def behind_page_parameters(after: str | None) -> list[str | int]:
    return [
        after or "00000000-0000-0000-0000-000000000000",
        CANDIDATE_PAGE_SIZE,
        json.dumps(
            [{"key": r.key, "feature_keys": sorted(r.feature_keys)} for r in get_entitlement_reactor_registry()]
        ),
    ]


def list_behind_organizations_page(after: str | None) -> BehindOrganizationsPage:
    if not get_entitlement_reactor_registry().reactors:
        return BehindOrganizationsPage(organization_ids=[], cursor=None, candidate_count=0)
    with connections["default"].cursor() as cursor:
        cursor.execute(BEHIND_PAGE_SQL, behind_page_parameters(after))
        ids, last, count = cursor.fetchone()
    return BehindOrganizationsPage(
        organization_ids=json.loads(ids) if isinstance(ids, str) else ids, cursor=last, candidate_count=count
    )
