import os

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


application = lifetime_wrapper(get_asgi_application())
