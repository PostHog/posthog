from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from posthog.frontend_views import is_indexable_page


class RobotsTagMiddleware:
    """Tells search engines not to index any response except the public login and signup pages.

    A logged-out crawler gets a redirect to /login for every app URL. Search engines can keep
    the original URL listed after a temporary redirect, so the header goes on every response,
    redirects included, and not only on the rendered app page.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not is_indexable_page(request.path):
            response.headers.setdefault("X-Robots-Tag", "noindex")
        return response
