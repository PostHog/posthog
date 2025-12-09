from django.db.models import CharField, Count, OuterRef, QuerySet, Subquery
from django.db.models.functions import Cast

import structlog
from rest_framework import pagination, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket

logger = structlog.get_logger(__name__)


class TicketPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class TicketSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()
    last_message_text = serializers.SerializerMethodField()

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
            "last_message_text",
            "unread_team_count",
        ]
        read_only_fields = [
            "id",
            "channel_source",
            "distinct_id",
            "created_at",
            "message_count",
            "last_message_at",
            "last_message_text",
            "unread_team_count",
        ]

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

    def get_last_message_text(self, obj: Ticket) -> str | None:
        """Get text of last message."""
        if hasattr(obj, "last_message_text"):
            return obj.last_message_text
        last_comment = (
            Comment.objects.filter(team=obj.team, scope="conversations_ticket", item_id=str(obj.id), deleted=False)
            .order_by("-created_at")
            .first()
        )
        return last_comment.content if last_comment else None


class TicketViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "ticket"
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = TicketPagination

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter tickets by team and add annotations."""
        queryset = queryset.filter(team_id=self.team_id)

        # Add message count annotation using Subquery
        # Cast ticket UUID id to string to match Comment.item_id CharField
        message_count_subquery = (
            Comment.objects.filter(
                team_id=self.team_id,
                scope="conversations_ticket",
                item_id=Cast(OuterRef("id"), output_field=CharField()),
                deleted=False,
            )
            .values("item_id")
            .annotate(count=Count("id"))
            .values("count")
        )
        queryset = queryset.annotate(message_count=Subquery(message_count_subquery))

        # Add last message timestamp annotation using Subquery
        last_message_subquery = (
            Comment.objects.filter(
                team_id=self.team_id,
                scope="conversations_ticket",
                item_id=Cast(OuterRef("id"), output_field=CharField()),
                deleted=False,
            )
            .order_by("-created_at")
            .values("created_at")[:1]
        )
        queryset = queryset.annotate(last_message_at=Subquery(last_message_subquery))

        # Add last message text annotation using Subquery
        last_message_text_subquery = (
            Comment.objects.filter(
                team_id=self.team_id,
                scope="conversations_ticket",
                item_id=Cast(OuterRef("id"), output_field=CharField()),
                deleted=False,
            )
            .order_by("-created_at")
            .values("content")[:1]
        )
        queryset = queryset.annotate(last_message_text=Subquery(last_message_text_subquery))

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

        return queryset.order_by("-updated_at")

    def retrieve(self, request, *args, **kwargs):
        """Get single ticket and mark as read by team."""
        instance = self.get_object()
        if instance.unread_team_count > 0:
            instance.unread_team_count = 0
            instance.save(update_fields=["unread_team_count"])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
