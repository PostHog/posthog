import os

from django.conf import settings
from django.core.asgi import get_asgi_application
from django.http.response import HttpResponse

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


# PostHogConfig.ready() handles setting the global analytics key in WSGI. The same code couldn't run
# in ASGI because ready() doesn't expose an async interface.
def self_capture_wrapper(func):
    if not settings.DEBUG or not settings.SELF_CAPTURE:
        return func

    async def inner(scope, receive, send):
        if not getattr(inner, "debug_analytics_initialized", False):
            from posthog.utils import initialize_self_capture_api_token

            await initialize_self_capture_api_token()
            # Set a flag to indicate that the analytics key has been set, so we don't run the code on every request.
            inner.debug_analytics_initialized = True  # type: ignore
        return await func(scope, receive, send)

    return inner


application = lifetime_wrapper(self_capture_wrapper(get_asgi_application()))
