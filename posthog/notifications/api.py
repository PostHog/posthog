"""
REST API for notifications.
"""

from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.notification import Notification
from posthog.notifications.serializers import NotificationSerializer

logger = structlog.get_logger(__name__)


class NotificationLimitOffsetPagination(LimitOffsetPagination):
    """Pagination for notifications with default page size of 20."""

    default_limit = 20
    max_limit = 100


@api_view(["POST"])
@permission_classes([AllowAny])
def broadcast_notification(request):
    """
    Internal endpoint for plugin-server to broadcast notifications via WebSocket.

    Expected payload:
    {
        "user_id": 1,
        "notification": {
            "id": "uuid",
            "resource_type": "feature_flag",
            "resource_id": "flag-uuid",
            "title": "Feature flag updated",
            "message": "John updated the 'new-signup-flow' feature flag",
            "context": {...},
            "priority": "normal",
            "created_at": "2025-01-19T..."
        }
    }
    """
    user_id = request.data.get("user_id")
    notification_data = request.data.get("notification")

    if not user_id or not notification_data:
        return Response(
            {"error": "user_id and notification are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        channel_layer = get_channel_layer()
        group_name = f"user_{user_id}"

        logger.info(
            "websocket_broadcast_attempt",
            user_id=user_id,
            notification_id=notification_data.get("id"),
            group_name=group_name,
        )

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "notification",
                "notification": notification_data,
            },
        )
        logger.info(
            "websocket_broadcast_success",
            user_id=user_id,
            notification_id=notification_data.get("id"),
        )

        return Response({"status": "broadcast"}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception(
            "websocket_broadcast_failed",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


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

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def broadcast(self, request, *args, **kwargs):
        """
        Internal endpoint for plugin-server to broadcast notifications via WebSocket.

        Expected payload:
        {
            "user_id": 1,
            "notification": {
                "id": "uuid",
                "resource_type": "feature_flag",
                "resource_id": "flag-uuid",
                "title": "Feature flag updated",
                "message": "John updated the 'new-signup-flow' feature flag",
                "context": {...},
                "priority": "normal",
                "created_at": "2025-01-19T..."
            }
        }
        """
        user_id = request.data.get("user_id")
        notification_data = request.data.get("notification")

        if not user_id or not notification_data:
            return Response(
                {"error": "user_id and notification are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            channel_layer = get_channel_layer()
            group_name = f"user_{user_id}"

            logger.info(
                "websocket_broadcast_attempt",
                user_id=user_id,
                notification_id=notification_data.get("id"),
                group_name=group_name,
            )

            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "notification",
                    "notification": notification_data,
                },
            )

            logger.info(
                "websocket_broadcast_success",
                user_id=user_id,
                notification_id=notification_data.get("id"),
            )

            return Response({"status": "broadcast"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(
                "websocket_broadcast_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
