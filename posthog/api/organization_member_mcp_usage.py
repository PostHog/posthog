import hashlib
from datetime import datetime
from uuid import UUID

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.models.team import Team

INTERNAL_ANALYTICS_TEAM_ID = 2
MCP_USAGE_CACHE_TTL_SECONDS = 300


def get_last_mcp_use_by_member(organization_id: UUID, distinct_ids: list[str]) -> dict[str, datetime]:
    if not distinct_ids:
        return {}

    # Organizations that restrict the member list can expose different rosters to different viewers.
    member_ids = sorted(distinct_ids)
    roster_hash = hashlib.sha256(repr(member_ids).encode()).hexdigest()
    cache_key = f"organization-member-mcp-usage:{organization_id}:{roster_hash}"
    return cache.get_or_set(
        cache_key, lambda: _query_last_mcp_use(organization_id, member_ids), MCP_USAGE_CACHE_TTL_SECONDS
    )


def _query_last_mcp_use(organization_id: UUID, distinct_ids: list[str]) -> dict[str, datetime]:
    result = execute_hogql_query(
        """
        SELECT distinct_id, max(timestamp)
        FROM events
        WHERE event = '$mcp_tool_call'
          AND timestamp >= now() - INTERVAL 90 DAY
          AND distinct_id IN {member_ids}
          AND properties.$mcp_organization_id = {organization_id}
          AND properties.mcp_runtime = 'hono'
          AND properties.$mcp_scope_preset = 'user'
          AND properties.$mcp_tool_name != 'exec'
          AND toBool(properties.$mcp_is_error) = false
        GROUP BY distinct_id
        """,
        team=Team.objects.get(pk=INTERNAL_ANALYTICS_TEAM_ID),
        placeholders={
            "organization_id": ast.Constant(value=str(organization_id)),
            "member_ids": ast.Array(exprs=[ast.Constant(value=distinct_id) for distinct_id in distinct_ids]),
        },
        query_type="organization_members_last_mcp_use",
        workload=Workload.ONLINE,
        settings=HogQLGlobalSettings(max_execution_time=3, timeout_overflow_mode="throw"),
        limit_context=None,
    )
    return dict(result.results or [])
