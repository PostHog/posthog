"""
WebSocket consumer for real-time notifications.
"""

import json
import asyncio

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

import structlog
import redis.asyncio as aioredis
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = structlog.get_logger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for user notifications.

    Protocol:
    - Client connects to /ws/notifications/?token=<auth_token>
    - Server authenticates user
    - Server subscribes to Redis pub/sub channel: posthog:notifications:user:{user_id}
    - Plugin-server publishes notifications directly to Redis pub/sub
    - WebSocket receives and forwards notifications to client in real-time

    Message format (server -> client):
    {
        "id": "uuid",
        "resource_type": "feature_flag",
        "resource_id": "flag-uuid",
        "title": "Feature flag updated",
        "message": "John updated the 'new-signup-flow' feature flag",
        "context": {...},
        "priority": "normal",
        "created_at": "2025-01-19T...",
    }
    """

    async def connect(self):
        """Authenticate user and subscribe to Redis pub/sub for notifications."""
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
        self.redis_channel = f"posthog:notifications:user:{user.id}"

        await self.accept()

        # Subscribe to Redis pub/sub for direct notifications from plugin-server
        try:
            redis_url = getattr(settings, "NOTIFICATIONS_REDIS_URL", settings.REDIS_URL)
            self.redis = await aioredis.from_url(redis_url, decode_responses=True)
            self.pubsub = self.redis.pubsub()
            await self.pubsub.subscribe(self.redis_channel)

            # Start background task to listen for Redis messages
            self.redis_listener_task = asyncio.create_task(self._listen_redis_pubsub())

            logger.info(
                "websocket_redis_subscribed",
                user_id=user.id,
                redis_channel=self.redis_channel,
            )
        except Exception as e:
            logger.warning(
                "websocket_redis_subscription_failed",
                user_id=user.id,
                error=str(e),
                error_type=type(e).__name__,
            )

        logger.info(
            "websocket_connection_established",
            user_id=user.id,
            redis_channel=self.redis_channel,
        )

    async def disconnect(self, close_code):
        """Unsubscribe from Redis pub/sub and cleanup connections."""
        # Cancel Redis listener task
        if hasattr(self, "redis_listener_task"):
            self.redis_listener_task.cancel()
            try:
                await self.redis_listener_task
            except asyncio.CancelledError:
                pass

        # Unsubscribe from Redis pub/sub
        if hasattr(self, "pubsub"):
            try:
                await self.pubsub.unsubscribe(self.redis_channel)
                await self.pubsub.close()
            except Exception as e:
                logger.warning(
                    "websocket_redis_unsubscribe_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        # Close Redis connection
        if hasattr(self, "redis"):
            try:
                await self.redis.close()
            except Exception as e:
                logger.warning(
                    "websocket_redis_close_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )

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

    async def _listen_redis_pubsub(self):
        """
        Background task that listens for Redis pub/sub messages.

        Receives notifications published directly from plugin-server via Redis pub/sub
        and forwards them to the WebSocket client.
        """
        logger.info("websocket_redis_listener_started", user_id=self.user.id)
        try:
            async for message in self.pubsub.listen():
                logger.info(
                    "websocket_redis_message_received",
                    user_id=self.user.id,
                    message_type=message.get("type"),
                    channel=message.get("channel"),
                )
                if message["type"] == "message":
                    try:
                        notification_data = json.loads(message["data"])
                        await self.send(text_data=json.dumps(notification_data))

                        logger.info(
                            "websocket_redis_notification_sent",
                            user_id=self.user.id,
                            notification_id=notification_data.get("id"),
                            source="redis_pubsub",
                        )
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "websocket_redis_invalid_json",
                            user_id=self.user.id,
                            error=str(e),
                        )
                    except Exception as e:
                        logger.exception(
                            "websocket_redis_send_error",
                            user_id=self.user.id,
                            error=str(e),
                            error_type=type(e).__name__,
                        )
        except asyncio.CancelledError:
            logger.info("websocket_redis_listener_cancelled", user_id=self.user.id)
            raise
        except Exception as e:
            logger.exception(
                "websocket_redis_listener_error",
                user_id=self.user.id,
                error=str(e),
                error_type=type(e).__name__,
            )
