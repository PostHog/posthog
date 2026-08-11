from __future__ import annotations

from typing import Any

from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.conversations.backend.api.ticket_filters import apply_ticket_filters
from products.conversations.backend.models import Ticket
from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget


def _serialize_ticket(ticket: Ticket) -> dict[str, Any]:
    assignment = getattr(ticket, "assignment", None)
    assignee = None
    if assignment is not None:
        assignee = {
            "user": (
                {"id": assignment.user.id, "name": assignment.user.first_name or assignment.user.email}
                if assignment.user
                else None
            ),
            "role": ({"id": assignment.role.id, "name": assignment.role.name} if assignment.role else None),
        }
    return {
        "id": str(ticket.id),
        "ticket_number": ticket.ticket_number,
        "channel_source": ticket.channel_source,
        "status": ticket.status,
        "priority": ticket.priority,
        "assignee": assignee,
        "updated_at": ticket.updated_at.isoformat(),
        "last_message_text": ticket.last_message_text,
        "unread_team_count": ticket.unread_team_count,
        "email_subject": ticket.email_subject,
    }


def run_conversations_recent_tickets_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE, config)
    limit = typed_config["limit"]

    queryset = Ticket.objects.filter(team=team).select_related("assignment", "assignment__user", "assignment__role")
    if user is not None:
        queryset = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(queryset)
    filters: dict[str, Any] = {"sorting": {"columnKey": "updated_at", "order": -1}}
    if typed_config["status"] != "all":
        filters["status"] = [typed_config["status"]]
    queryset = apply_ticket_filters(queryset, filters, team=team, user=user)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        rows = list(queryset[: page_limit + 1])
        return ListWidgetPage(results=rows[:page_limit], has_more=len(rows) > page_limit, next_offset=page_limit)

    return run_list_widget(
        limit=limit,
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=_serialize_ticket,
        log_key="conversations_recent_tickets_widget_total_count_failed",
    )
