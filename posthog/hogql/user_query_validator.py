"""Pre-execution validation for user-submitted HogQL queries.

Applied by ``HogQLQueryRunner._calculate`` when ``is_query_service`` is true —
i.e. the query came in via the external ``/query`` endpoint authenticated with a
personal API key. Violations raise ``QueryError`` (HTTP 400) before any database
work happens.

The validator itself does *not* check ``is_query_service`` — callers gate on that
and only invoke this for user-submitted queries.
"""

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.team import Team

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


def _is_org_exempted_from_offset_block(team: Team) -> bool:
    """Return True if the team's org is on the OFFSET allow-list.

    The flag is evaluated against the organization group — the distinct_id parameter
    is required by the SDK but doesn't affect the result (and we disable flag-event
    tracking so it doesn't affect telemetry either). We pass the organization id as
    the distinct_id: stable, always present, and self-documenting.

    Fail-open on flag-service errors: a failed check returns True so an outage of
    the flag service doesn't start rejecting previously-valid traffic.
    """
    org_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return True


def validate_user_query(node: ast.SelectQuery | ast.SelectSetQuery, team: Team) -> None:
    """Enforce user-query restrictions on a parsed HogQL AST.

    Currently: reject any OFFSET clause unless the team's organization is on the
    allow-list feature flag. Callers are expected to have already gated on
    ``is_query_service`` — this function unconditionally applies the policy.
    """
    if _is_org_exempted_from_offset_block(team):
        return
    _OffsetDetectingVisitor().visit(node)
