import re

from django.middleware.gzip import GZipMiddleware

allowed_paths = [re.compile(r"snapshots/?$")]


def allowed_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in allowed_paths)


class PostHogGZipMiddleware(GZipMiddleware):
    """
    The Django GZip Middleware comes with security warnings
    see: https://docs.djangoproject.com/en/4.0/ref/middleware/#module-django.middleware.gzip

    Rather than solve for those across the whole app. We can add it to specific paths
    """

    def process_response(self, request, response):
        if request.method == "GET" and allowed_path(request.path):
            return super().process_response(request, response)
        else:
            return response
