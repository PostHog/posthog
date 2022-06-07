import re
from typing import List

from django.conf import settings
from django.middleware.gzip import GZipMiddleware


class InvalidGzipAllowList(Exception):
    pass


def allowed_path(path: str, allowed_paths: List) -> bool:
    return any(pattern.search(path) for pattern in allowed_paths)


class PostHogGZipMiddleware(GZipMiddleware):
    def __init__(self, get_response=None) -> None:
        super().__init__(get_response)
        try:
            self.allowed_paths = [re.compile(pattern) for pattern in settings.GZIP_RESPONSE_ALLOW_LIST]
        except re.error as ex:
            raise InvalidGzipAllowList(str(ex)) from ex

    """
    The Django GZip Middleware comes with security warnings
    see: https://docs.djangoproject.com/en/4.0/ref/middleware/#module-django.middleware.gzip

    Rather than solve for those across the whole app. We can add it to specific paths
    """

    def process_response(self, request, response):
        if request.method == "GET" and allowed_path(request.path, self.allowed_paths):
            return super().process_response(request, response)
        else:
            return response
