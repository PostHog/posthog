import os

from django.core.asgi import get_asgi_application
from django.http.response import HttpResponse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "ASGI")


def lifetime_wrapper(func):
    async def inner(scope, receive, send):
        if scope["type"] != "http":
            return HttpResponse(status=501)
        return func(scope, receive, send)


application = lifetime_wrapper(get_asgi_application())
