"""Pre-execution validation passes for HogQL queries.

These run against the post-placeholder AST before ClickHouse SQL generation, so
violations surface as ``QueryError`` (HTTP 400) before any database work happens.
"""

import posthoganalytics
from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.query_tagging import AccessMethod, get_query_tag_value
from posthog.models.team import Team
from posthog.models.user import User

OFFSET_NOT_ALLOWED_MESSAGE = (
    "OFFSET is not supported on queries made with a personal API key. "
    "For pagination, use keyset pagination on the `timestamp` column, e.g. "
    "`WHERE timestamp > :last_seen_timestamp ORDER BY timestamp LIMIT N`. "
    "For bulk data extraction, use batch exports: https://posthog.com/docs/cdp/batch-exports"
)

# Org-level allow-list. When the flag is enabled for an organization, that org
# is exempted from the OFFSET block — their personal-API-key queries may use
# OFFSET as before. Default (flag not enabled) is to reject. Used to grandfather
# customers (Fivetran/Runway/etc.) while they migrate to keyset pagination or
# batch exports.
HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG = "hogql-personal-api-key-offset-allowed"

PERSONAL_API_KEY_OFFSET_REJECTIONS = Counter(
    "posthog_hogql_personal_api_key_offset_rejections_total",
    "HogQL queries rejected because they used OFFSET with a personal API key.",
)


class _OffsetDetectingVisitor(TraversingVisitor):
    """Raise ``QueryError`` on the first OFFSET clause found anywhere in the AST.

    Covers top-level ``OFFSET`` on ``SelectQuery`` and ``SelectSetQuery`` (UNION/etc.),
    as well as ``LIMIT N BY ... OFFSET M``. ``SAMPLE n OFFSET m`` is intentionally
    *not* flagged — that OFFSET selects a sample partition, not a pagination window.
    """

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.offset is not None:
            raise QueryError(OFFSET_NOT_ALLOWED_MESSAGE, node=node.offset)
        if node.limit_by is not None and node.limit_by.offset_value is not None:
            raise QueryError(OFFSET_NOT_ALLOWED_MESSAGE, node=node.limit_by.offset_value)
        super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        if node.offset is not None:
            raise QueryError(OFFSET_NOT_ALLOWED_MESSAGE, node=node.offset)
        super().visit_select_set_query(node)


def _is_personal_api_key_request() -> bool:
    return get_query_tag_value("access_method") == AccessMethod.PERSONAL_API_KEY


def _is_org_exempted_from_offset_block(team: Team, user: User | None) -> bool:
    """Return True if the team's org is on the OFFSET allow-list.

    Fail-open on any error (missing user, flag service outage, etc.): a failed check
    returns True so we don't break personal-API-key traffic on infrastructure issues.
    """
    distinct_id = getattr(user, "distinct_id", None) if user is not None else None
    if not distinct_id:
        return True
    try:
        return bool(
            posthoganalytics.feature_enabled(
                HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG,
                str(distinct_id),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return True


def validate_personal_api_key_query(
    node: ast.SelectQuery | ast.SelectSetQuery,
    team: Team,
    user: User | None,
) -> None:
    """Reject queries made with a personal API key that use OFFSET anywhere in the AST.

    No-op if any of the following holds:
    1. The request is not authenticated with a personal API key.
    2. The team's organization is on the OFFSET allow-list (grandfathered).
    3. The AST contains no OFFSET clause.
    """
    if not _is_personal_api_key_request():
        return
    if _is_org_exempted_from_offset_block(team, user):
        return
    try:
        _OffsetDetectingVisitor().visit(node)
    except QueryError:
        PERSONAL_API_KEY_OFFSET_REJECTIONS.inc()
        raise
