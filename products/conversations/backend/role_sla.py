from datetime import datetime
from uuid import UUID

from django.db.models import Count, Min, OuterRef, QuerySet, Subquery

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.role import RoleMembership
from products.conversations.backend.facade.types import RoleSlaBreach
from products.conversations.backend.models import Status, Ticket


def list_role_sla_breaches(
    team_id: int, user_id: int, *, due_after: datetime, due_before: datetime
) -> list[RoleSlaBreach]:
    """Tickets assigned to a role the viewer belongs to, due inside the window.

    Already-due tickets stay out: the window is the time left, not the time since a breach.
    Resolved tickets stay out: there is no reply left to make.
    """
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    role_ids = list(
        RoleMembership.objects.valid_for_authorization()
        .filter(user_id=user_id, role__organization_id=team.organization_id)
        .values_list("role_id", flat=True)
    )
    if not role_ids:
        return []

    visible = _visible_tickets(team, user, role_ids, due_after, due_before)
    soonest_number = Subquery(
        _visible_tickets(team, user, role_ids, due_after, due_before)
        .filter(assignment__role_id=OuterRef("assignment__role_id"))
        .order_by("sla_due_at", "ticket_number")
        .values("ticket_number")[:1]
    )
    rows = (
        visible.values("assignment__role_id", "assignment__role__name")
        .annotate(
            ticket_count=Count("id"),
            soonest_due_at=Min("sla_due_at"),
            soonest_ticket_number=soonest_number,
        )
        .order_by("soonest_due_at", "assignment__role__name")
    )
    return [
        RoleSlaBreach(
            role_id=row["assignment__role_id"],
            role_name=row["assignment__role__name"],
            ticket_count=row["ticket_count"],
            soonest_ticket_number=row["soonest_ticket_number"],
            soonest_due_at=row["soonest_due_at"],
        )
        for row in rows
    ]


def _visible_tickets(
    team: Team, user: User, role_ids: list[UUID], due_after: datetime, due_before: datetime
) -> QuerySet[Ticket]:
    due = Ticket.objects.filter(
        team_id=team.id,
        sla_due_at__gte=due_after,
        sla_due_at__lte=due_before,
        assignment__role_id__in=role_ids,
    ).exclude(status=Status.RESOLVED)
    return UserAccessControl(user, team=team).filter_queryset_by_access_level(due, resource="ticket")
