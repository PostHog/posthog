from django.db import transaction
from django.db.models import Q, QuerySet

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import pagination, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.utils import relative_date_parse

from products.conversations.backend.api.serializers import TicketAssignmentSerializer
from products.conversations.backend.models import Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel, Priority, Status

from ee.models.rbac.role import Role

logger = structlog.get_logger(__name__)


class TicketPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class TicketSerializer(serializers.ModelSerializer):
    assignee = TicketAssignmentSerializer(source="assignment", read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_number",
            "channel_source",
            "distinct_id",
            "status",
            "priority",
            "assignee",
            "anonymous_traits",
            "ai_resolved",
            "escalation_reason",
            "created_at",
            "updated_at",
            "message_count",
            "last_message_at",
            "last_message_text",
            "unread_team_count",
            "session_id",
            "session_context",
        ]
        read_only_fields = [
            "id",
            "ticket_number",
            "channel_source",
            "distinct_id",
            "created_at",
            "message_count",
            "last_message_at",
            "last_message_text",
            "unread_team_count",
            "assignee",
            "session_id",
            "session_context",
        ]


class TicketViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "ticket"
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    pagination_class = TicketPagination
    posthog_feature_flag = {
        "product-support": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
        ]
    }

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter tickets by team."""
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("assignment", "assignment__user", "assignment__role")

        status_param = self.request.query_params.get("status")
        if status_param and status_param in [s.value for s in Status]:
            queryset = queryset.filter(status=status_param)

        priority = self.request.query_params.get("priority")
        if priority and priority in [p.value for p in Priority]:
            queryset = queryset.filter(priority=priority)

        channel_source = self.request.query_params.get("channel_source")
        if channel_source and channel_source in [c.value for c in Channel]:
            queryset = queryset.filter(channel_source=channel_source)

        assignee = self.request.query_params.get("assignee")
        if assignee:
            if assignee.lower() == "unassigned":
                queryset = queryset.filter(assignment__isnull=True)
            elif assignee.startswith("user:"):
                try:
                    user_id = int(assignee[5:])
                    queryset = queryset.filter(assignment__user_id=user_id)
                except ValueError:
                    pass
            elif assignee.startswith("role:"):
                role_id = assignee[5:]
                queryset = queryset.filter(assignment__role_id=role_id)

        date_from = self.request.query_params.get("date_from")
        if date_from:
            parsed = relative_date_parse(date_from, self.team.timezone_info)
            if parsed:
                queryset = queryset.filter(updated_at__gte=parsed)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            parsed = relative_date_parse(date_to, self.team.timezone_info)
            if parsed:
                queryset = queryset.filter(updated_at__lte=parsed)

        distinct_id = self.request.query_params.get("distinct_id")
        if distinct_id and len(distinct_id) <= 200:
            queryset = queryset.filter(distinct_id__icontains=distinct_id)

        search = self.request.query_params.get("search")
        if search and len(search) <= 200:
            if search.isdigit():
                queryset = queryset.filter(ticket_number=int(search))
            else:
                queryset = queryset.filter(
                    Q(anonymous_traits__name__icontains=search) | Q(anonymous_traits__email__icontains=search)
                )

        return queryset.order_by("-updated_at")

    def retrieve(self, request, *args, **kwargs):
        """Get single ticket and mark as read by team."""
        instance = self.get_object()
        if instance.unread_team_count > 0:
            instance.unread_team_count = 0
            instance.save(update_fields=["unread_team_count"])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """Handle ticket updates including assignee changes."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        # Handle assignee separately since it's not a direct model field
        assignee = request.data.pop("assignee", None) if "assignee" in request.data else ...

        # Update other fields normally
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Handle assignee update if provided (not ... sentinel)
        if assignee is not ...:
            assign_ticket(
                instance,
                assignee,
                self.organization,
                request.user,
                self.team_id,
                is_impersonated_session(request),
            )
            # Refresh instance to get updated assignment
            instance.refresh_from_db()

        # Re-serialize to include updated assignee
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


def validate_assignee(assignee) -> None:
    """Validate assignee payload structure."""
    if assignee is None:
        return
    if not isinstance(assignee, dict):
        raise serializers.ValidationError({"assignee": "must be an object"})
    if "type" not in assignee or "id" not in assignee:
        raise serializers.ValidationError({"assignee": "must have 'type' and 'id'"})
    if assignee["type"] not in ("user", "role"):
        raise serializers.ValidationError({"assignee": "type must be 'user' or 'role'"})


def validate_assignee_membership(assignee, organization) -> None:
    """Validate that the assignee belongs to the organization."""
    if assignee is None:
        return

    if assignee["type"] == "user":
        if not OrganizationMembership.objects.filter(organization=organization, user_id=assignee["id"]).exists():
            raise serializers.ValidationError({"assignee": "user is not a member of this organization"})
    elif assignee["type"] == "role":
        if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
            raise serializers.ValidationError({"assignee": "role does not belong to this organization"})


def assign_ticket(ticket: Ticket, assignee, organization, user, team_id, was_impersonated):
    """
    Assign a ticket to a user or role.

    Args:
        ticket: The ticket to assign
        assignee: Dict with 'type' ('user' or 'role') and 'id', or None to unassign
        organization: The organization
        user: The user making the change
        team_id: The team ID
        was_impersonated: Whether the session is impersonated
    """
    validate_assignee(assignee)
    validate_assignee_membership(assignee, organization)

    with transaction.atomic():
        # Lock the ticket to prevent concurrent modifications
        Ticket.objects.select_for_update().get(id=ticket.id)
        assignment_before = TicketAssignment.objects.filter(ticket_id=ticket.id).first()
        serialized_assignment_before = TicketAssignmentSerializer(assignment_before).data if assignment_before else None

        if assignee:
            assignment_after, _ = TicketAssignment.objects.update_or_create(
                ticket_id=ticket.id,
                defaults={
                    "user_id": None if assignee["type"] != "user" else assignee["id"],
                    "role_id": None if assignee["type"] != "role" else assignee["id"],
                },
            )
            serialized_assignment_after = TicketAssignmentSerializer(assignment_after).data
        else:
            if assignment_before:
                assignment_before.delete()
            serialized_assignment_after = None

        log_activity(
            organization_id=organization.id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="assigned",
            detail=Detail(
                name=f"Ticket #{ticket.ticket_number}",
                changes=[
                    Change(
                        type="Ticket",
                        field="assignee",
                        before=serialized_assignment_before,
                        after=serialized_assignment_after,
                        action="changed",
                    )
                ],
            ),
        )
