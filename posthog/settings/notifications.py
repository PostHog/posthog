"""
WebSocket and notification configuration for Django Channels.
"""

import os

from posthog.settings.utils import get_from_env, str_to_bool

NOTIFICATIONS_WEBSOCKET_ENABLED = str_to_bool(get_from_env("NOTIFICATIONS_WEBSOCKET_ENABLED", "true"))

NOTIFICATIONS_REDIS_URL = get_from_env(
    "NOTIFICATIONS_REDIS_URL",
    os.getenv("REDIS_URL", "redis://localhost:6379"),
)

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [NOTIFICATIONS_REDIS_URL],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

ASGI_APPLICATION = "posthog.routing.application"
