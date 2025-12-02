from django.db.models import Count, Max, QuerySet

import structlog
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket

logger = structlog.get_logger(__name__)


class TicketSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "channel_source",
            "distinct_id",
            "status",
            "anonymous_traits",
            "ai_resolved",
            "escalation_reason",
            "created_at",
            "updated_at",
            "message_count",
            "last_message_at",
        ]
        read_only_fields = ["id", "channel_source", "distinct_id", "created_at", "message_count", "last_message_at"]

    def get_message_count(self, obj: Ticket) -> int:
        """Get count of messages in this ticket."""
        if hasattr(obj, "message_count"):
            return obj.message_count
        return Comment.objects.filter(
            team=obj.team, scope="conversations_ticket", item_id=str(obj.id), deleted=False
        ).count()

    def get_last_message_at(self, obj: Ticket):
        """Get timestamp of last message."""
        if hasattr(obj, "last_message_at"):
            return obj.last_message_at
        last_comment = (
            Comment.objects.filter(team=obj.team, scope="conversations_ticket", item_id=str(obj.id), deleted=False)
            .order_by("-created_at")
            .first()
        )
        return last_comment.created_at if last_comment else None


class TicketViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Basic CRUD operations for tickets.
    List tickets with filtering and search.
    Update ticket status.
    """

    scope_object = "ticket"
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter tickets by team and add annotations."""
        queryset = queryset.filter(team_id=self.team_id)

        # Add message count annotation
        queryset = queryset.annotate(
            message_count=Count(
                "id",
                filter=Comment.objects.filter(
                    team_id=self.team_id, scope="conversations_ticket", item_id="id", deleted=False
                ).query,
            )
        )

        # Add last message timestamp annotation
        queryset = queryset.annotate(
            last_message_at=Max(
                "created_at",
                filter=Comment.objects.filter(
                    team_id=self.team_id, scope="conversations_ticket", item_id="id", deleted=False
                ).query,
            )
        )

        # Filter by status if provided
        status = self.request.query_params.get("status")
        if status:
            queryset = queryset.filter(status=status)

        # Search by distinct_id if provided
        distinct_id = self.request.query_params.get("distinct_id")
        if distinct_id:
            queryset = queryset.filter(distinct_id__icontains=distinct_id)

        # Search by customer name/email in anonymous_traits
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(anonymous_traits__name__icontains=search) | queryset.filter(
                anonymous_traits__email__icontains=search
            )

        return queryset.order_by("-created_at")
