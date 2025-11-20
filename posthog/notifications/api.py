"""
REST API for notifications.
"""

from django.utils import timezone

import structlog
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.notification import Notification
from posthog.notifications.serializers import NotificationSerializer

logger = structlog.get_logger(__name__)


class NotificationLimitOffsetPagination(LimitOffsetPagination):
    """Pagination for notifications with default page size of 20."""

    default_limit = 20
    max_limit = 100


class NotificationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for user notifications.

    Endpoints:
    - GET /api/projects/{project_id}/notifications/ - List notifications
    - GET /api/projects/{project_id}/notifications/?unread=true - List unread only
    - POST /api/projects/{project_id}/notifications/{id}/mark_read/ - Mark as read
    - POST /api/projects/{project_id}/notifications/mark_all_read/ - Mark all as read
    - GET /api/projects/{project_id}/notifications/unread_count/ - Get unread count
    """

    scope_object = "INTERNAL"
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationLimitOffsetPagination
    queryset = Notification.objects.all()

    def safely_get_queryset(self, queryset):
        """Filter notifications for current user and apply additional filters."""
        # Filter for current user
        queryset = queryset.filter(user=self.request.user)

        # Filter by unread
        if self.request.query_params.get("unread") == "true":
            queryset = queryset.filter(read_at__isnull=True)

        # Filter by resource_type
        resource_type = self.request.query_params.get("resource_type")
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)

        # Filter by priority
        priority = self.request.query_params.get("priority")
        if priority:
            queryset = queryset.filter(priority=priority)

        return queryset.order_by("-created_at")

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request, *args, **kwargs):
        """Mark all unread notifications as read for current user."""
        count = Notification.objects.filter(
            user=request.user,
            team=self.team,
            read_at__isnull=True,
        ).update(read_at=timezone.now())

        return Response(
            {"marked_read": count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"])
    def unread_count(self, request, *args, **kwargs):
        """Get count of unread notifications."""
        count = Notification.objects.filter(
            user=request.user,
            team=self.team,
            read_at__isnull=True,
        ).count()

        return Response(
            {"unread_count": count},
            status=status.HTTP_200_OK,
        )
