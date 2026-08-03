"""Analytics capture for data catalog lifecycle events.

Single owner of the server-side ``data catalog *`` events, so every write path (REST, MCP,
future system callers) emits one uniform, attributed event. Passing the DRF ``request`` attaches
transport attribution (``source``, ``access_method``, ``mcp_*`` client properties). Callers with
no user still emit, keyed to the team, with ``is_system: true`` so dashboards can exclude them
from people-facing counts.
"""

from typing import TYPE_CHECKING, Any, Optional

from posthog.event_usage import get_request_analytics_properties, report_user_action, report_user_or_team_action
from posthog.models import Team, User

if TYPE_CHECKING:
    from rest_framework.request import Request

    from ..models import Metric, RelationshipProposal, TableCertification

METRIC_CREATED_EVENT = "data catalog metric created"
METRIC_UPDATED_EVENT = "data catalog metric updated"
METRIC_APPROVED_EVENT = "data catalog metric approved"
METRIC_APPROVAL_BLOCKED_EVENT = "data catalog metric approval blocked"
METRIC_DELETED_EVENT = "data catalog metric deleted"
METRIC_RUN_EVENT = "data catalog metric run"
METRIC_RUN_FAILED_EVENT = "data catalog metric run failed"
CERTIFICATION_PROPOSED_EVENT = "data catalog certification proposed"
CERTIFICATION_CERTIFIED_EVENT = "data catalog certification certified"
CERTIFICATION_DEPRECATED_EVENT = "data catalog certification deprecated"
CERTIFICATION_REVOKED_EVENT = "data catalog certification revoked"
RELATIONSHIP_PROPOSED_EVENT = "data catalog relationship proposed"
RELATIONSHIP_ACCEPTED_EVENT = "data catalog relationship accepted"
RELATIONSHIP_REJECTED_EVENT = "data catalog relationship rejected"


def certification_target_name(cert: "TableCertification") -> str:
    if cert.table_id:
        return cert.table.name if cert.table else ""
    return cert.saved_query.name if cert.saved_query else ""


def capture_metric_event(
    event: str,
    metric: "Metric",
    *,
    team: Team,
    user: Optional[User],
    request: "Request | None" = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    _report(
        event,
        {
            "metric_id": str(metric.id),
            "metric_name": metric.name,
            "definition_kind": metric.definition_kind,
            "status": metric.status,
            "created_source": metric.created_source,
            "ai_model": metric.ai_model or None,
            "confidence": metric.confidence,
            "has_definition": metric.definition is not None,
            "is_from_insight": bool(metric.source_insight_short_id),
            **(extra or {}),
        },
        team=team,
        user=user,
        request=request,
    )


def capture_certification_event(
    event: str,
    cert: "TableCertification",
    *,
    team: Team,
    user: Optional[User],
    request: "Request | None" = None,
) -> None:
    _report(
        event,
        {
            "certification_id": str(cert.id),
            "status": cert.status,
            "target": certification_target_name(cert),
            "target_kind": "table" if cert.table_id else "view",
        },
        team=team,
        user=user,
        request=request,
    )


def capture_relationship_event(
    event: str,
    proposal: "RelationshipProposal",
    *,
    team: Team,
    user: Optional[User],
    request: "Request | None" = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    _report(
        event,
        {
            "proposal_id": str(proposal.id),
            "status": proposal.status,
            "source_table": proposal.source_table_name,
            "joining_table": proposal.joining_table_name,
            "confidence": proposal.confidence,
            "has_evidence": bool(proposal.evidence),
            **(extra or {}),
        },
        team=team,
        user=user,
        request=request,
    )


def _report(
    event: str,
    properties: dict[str, Any],
    *,
    team: Team,
    user: Optional[User],
    request: "Request | None",
) -> None:
    properties["is_system"] = user is None
    if user is not None:
        report_user_action(user, event, properties, team=team, request=request)
        return
    analytics_props = get_request_analytics_properties(request) if request is not None else None
    report_user_or_team_action(event, properties, user=None, team=team, analytics_props=analytics_props)
