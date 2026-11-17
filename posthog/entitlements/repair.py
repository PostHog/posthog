import json

from django.db import connections

from posthog.dataclasses import frozen
from posthog.entitlements.registry import get_entitlement_reactor_registry

CANDIDATE_PAGE_SIZE = 200

# Only organizations with a checkpoint can be behind, so pages walk checkpoint rows by organization_id.
# Each page is bounded before expansion, including pages with no behind rows.
BEHIND_PAGE_SQL = """
WITH reactors AS (
    SELECT * FROM jsonb_to_recordset(%s::jsonb) AS r(key text, feature_keys jsonb)
), candidates AS MATERIALIZED (
    SELECT DISTINCT organization_id
    FROM posthog_organizationentitlementappliedstate
    WHERE organization_id > %s::uuid AND reactor_key = ANY(ARRAY(SELECT key FROM reactors))
    ORDER BY organization_id
    LIMIT %s
), behind AS (
    SELECT o.id FROM candidates c
    JOIN posthog_organization o ON o.id = c.organization_id
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
       (SELECT organization_id::text FROM candidates ORDER BY organization_id DESC LIMIT 1),
       (SELECT count(*) FROM candidates)
"""


@frozen
class BehindOrganizationsPage:
    organization_ids: list[str]
    cursor: str | None
    candidate_count: int


def behind_page_parameters(after: str | None) -> list[str | int]:
    return [
        json.dumps(
            [{"key": r.key, "feature_keys": sorted(r.feature_keys)} for r in get_entitlement_reactor_registry()]
        ),
        after or "00000000-0000-0000-0000-000000000000",
        CANDIDATE_PAGE_SIZE,
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
