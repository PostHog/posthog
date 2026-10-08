from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import relative_date_parse

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.widget_specs.configs import WORKFLOWS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.workflows.backend.facade.api import list_workflow_activity
from products.workflows.backend.facade.contracts import WorkflowActivityRow

DEFAULT_DATE_FROM = "-7d"


def _serialize_row(row: WorkflowActivityRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "workflow_type": row.workflow_type,
        "trigger_type": row.trigger_type,
        "has_email_step": row.has_email_step,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "started": row.started,
        "completed": row.completed,
        "failed": row.failed,
        "email_sent": row.email_sent,
        "email_delivered": row.email_delivered,
        "email_opened": row.email_opened,
        "email_bounced": row.email_bounced,
    }


def _resolve_after(config: dict[str, Any], team: Team, now: datetime) -> datetime:
    date_range = config.get("dateRange")
    date_from = date_range.get("date_from") if isinstance(date_range, dict) else None
    return relative_date_parse(date_from or DEFAULT_DATE_FROM, team.timezone_info, now=now)


def run_workflows_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(WORKFLOWS_LIST_WIDGET_TYPE, config)
    limit = typed_config["limit"]
    now = timezone.now()

    page = list_workflow_activity(
        team_id=team.id,
        access_control=UserAccessControl(user=user, team=team) if user is not None else None,
        status=None if typed_config["status"] == "all" else typed_config["status"],
        workflow_type=None if typed_config["workflowType"] == "all" else typed_config["workflowType"],
        limit=limit,
        after=_resolve_after(typed_config, team, now),
        before=now,
    )
    results = [_serialize_row(row) for row in page.rows]
    return {
        "results": results,
        "hasMore": page.has_more,
        "limit": limit,
        "offset": 0,
        # Total is unknown without a count query; the footer shows "N+" when has_more is set.
        **({} if page.has_more else {"totalCount": len(results), "totalCountCapped": False}),
    }
