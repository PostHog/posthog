import os

from django.core.asgi import get_asgi_application
from django.http.response import HttpResponse
from channels.routing import ProtocolTypeRouter, URLRouter

from channels.auth import AuthMiddlewareStack
from posthog.api.query_ws import QueryConsumer
from django.urls import path


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "ASGI")


# Django doesn't support lifetime requests and raises an exception
# when it receives them. This creates a lot of noise in sentry so
# intercept these requests and return a 501 error without raising an exception
def lifetime_wrapper(func):
    async def inner(scope, receive, send):
        if scope["type"] != "http":
            return HttpResponse(status=501)
        return await func(scope, receive, send)

    return inner


websocket_urlpatterns = [
    path("ws/query/", QueryConsumer.as_asgi()),
]

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)

# application = lifetime_wrapper(get_asgi_application())
