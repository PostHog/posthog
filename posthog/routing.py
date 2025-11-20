"""
ASGI routing configuration for WebSocket and HTTP.
"""

import os

from django.core.asgi import get_asgi_application
from django.urls import path

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

django_asgi_app = get_asgi_application()

from posthog.notifications.consumers import NotificationConsumer  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(
                [
                    path("ws/notifications/", NotificationConsumer.as_asgi()),
                ]
            )
        ),
    }
)
