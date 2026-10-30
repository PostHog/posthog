"""Opens an authorization session for each request."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .logic import session


class AuthorizationSessionMiddleware:
    """Binds `subject=None` to the request's user for every check the request makes."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # DRF replaces request.user when it authenticates, after this middleware runs, so the
        # session reads the attribute at check time.
        with session.scope(principal=lambda: getattr(request, "user", None)):
            return self.get_response(request)
