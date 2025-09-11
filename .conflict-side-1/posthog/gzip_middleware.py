import re

from django.conf import settings
from django.middleware.gzip import GZipMiddleware


class InvalidGZipAllowList(Exception):
    pass


def allowed_path(path: str, allowed_paths: list) -> bool:
    return any(pattern.search(path) for pattern in allowed_paths)


class ScopedGZipMiddleware(GZipMiddleware):
    """
    The Django GZip Middleware comes with security warnings
    see: https://docs.djangoproject.com/en/4.0/ref/middleware/#module-django.middleware.gzip

    Rather than solve for those across the whole app. We can add it to specific paths

    http://breachattack.com/resources/BREACH%20-%20SSL,%20gone%20in%2030%20seconds.pdf

    The vulnerability requires two things

        • Reflect user-input in HTTP response bodies
        • Reflect a secret (such as a CSRF token) in HTTP response bodies

    e.g. a CSRF token in the URL and in the response body, or form input value in the request and in the response

    If an API path does that, an attacker can use knowledge of the compression algorithm
        to recover the secret from the compressed response

    If a given API path doesn't do that it is safe to compress.
        Add a pattern that matches it to GZIP_RESPONSE_ALLOW_LIST
    """

    def __init__(self, get_response=None) -> None:
        super().__init__(get_response)
        try:
            self.allowed_paths = [re.compile(pattern) for pattern in settings.GZIP_RESPONSE_ALLOW_LIST]
            self.allowed_post_paths = [re.compile(pattern) for pattern in settings.GZIP_POST_RESPONSE_ALLOW_LIST]
        except re.error as ex:
            raise InvalidGZipAllowList(str(ex)) from ex

    def process_response(self, request, response):
        if request.method == "GET" and allowed_path(request.path, self.allowed_paths):
            return super().process_response(request, response)
        elif request.method == "POST" and allowed_path(request.path, self.allowed_post_paths):
            return super().process_response(request, response)
        else:
            return response
