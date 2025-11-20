"""
WebSocket consumer for real-time notifications.
"""

import json

from django.contrib.auth.models import AnonymousUser

import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = structlog.get_logger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for user notifications.

    Protocol:
    - Client connects to /ws/notifications/?token=<auth_token>
    - Server authenticates user
    - Server subscribes user to their personal channel: user_{user_id}
    - Server publishes notifications via Redis Pub/Sub
    - Client receives real-time notification messages

    Message format (server -> client):
    {
        "type": "notification",
        "notification": {
            "id": "uuid",
            "resource_type": "feature_flag",
            "resource_id": "flag-uuid",
            "title": "Feature flag updated",
            "message": "John updated the 'new-signup-flow' feature flag",
            "context": {...},
            "priority": "normal",
            "created_at": "2025-01-19T...",
        }
    }
    """

    async def connect(self):
        """Authenticate and subscribe user to their notification channel."""
        logger.info("websocket_connect_attempt", headers=dict(self.scope.get("headers", [])))

        user = await self.get_authenticated_user()

        logger.info(
            "websocket_auth_result",
            user_id=user.id if user and not user.is_anonymous else None,
            is_anonymous=user.is_anonymous if user else True,
            user_type=type(user).__name__ if user else "None",
        )

        if not user or user.is_anonymous:
            logger.warning("websocket_connection_rejected", reason="unauthenticated")
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f"user_{user.id}"

        # Subscribe this WebSocket channel to the user's group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(
            "websocket_connection_established",
            user_id=user.id,
            group=self.group_name,
        )

    async def disconnect(self, close_code):
        """Unsubscribe user from their notification channel."""
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

            logger.info(
                "websocket_connection_closed",
                user_id=getattr(self, "user", None),
                close_code=close_code,
            )

    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle incoming messages from client.

        Currently a no-op as this is a one-way channel (server -> client).
        Future: Could handle mark_read acknowledgments.
        """
        if text_data:
            try:
                data = json.loads(text_data)
                logger.debug(
                    "websocket_message_received",
                    user_id=self.user.id,
                    message_type=data.get("type"),
                )
            except json.JSONDecodeError:
                logger.warning(
                    "websocket_invalid_json",
                    user_id=self.user.id,
                )

    async def notification(self, event):
        """
        Handler for notification messages from Redis Pub/Sub.

        Called when a message is published to the user's channel.
        """
        await self.send(text_data=json.dumps(event["notification"]))

        logger.debug(
            "websocket_notification_sent",
            user_id=self.user.id,
            notification_id=event["notification"].get("id"),
        )

    @database_sync_to_async
    def get_authenticated_user(self):
        """
        Authenticate user from query string token.

        Tries multiple authentication strategies:
        1. Session authentication (from cookies)
        2. Token authentication (from ?token= query param)

        Returns:
            User instance or AnonymousUser
        """

        scope = self.scope
        user = scope.get("user")

        logger.info(
            "websocket_auth_check_session",
            has_user=user is not None,
            is_anonymous=isinstance(user, AnonymousUser) if user else None,
        )

        if user and not isinstance(user, AnonymousUser):
            logger.info("websocket_auth_session_success", user_id=user.id)
            return user

        query_string = scope.get("query_string", b"").decode()
        logger.info("websocket_auth_check_token", query_string=query_string[:100])

        if "token=" in query_string:
            token = query_string.split("token=")[1].split("&")[0]
            logger.info("websocket_auth_token_extracted", token_prefix=token[:8] if len(token) > 8 else token)

            try:
                from rest_framework.authtoken.models import Token

                token_obj = Token.objects.select_related("user").get(key=token)
                logger.info("websocket_auth_token_success", user_id=token_obj.user.id)
                return token_obj.user
            except Exception as e:
                logger.warning(
                    "websocket_token_auth_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        logger.info("websocket_auth_failed_returning_anonymous")
        return AnonymousUser()
