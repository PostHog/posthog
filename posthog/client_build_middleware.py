import re
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from prometheus_client import Counter

from posthog.git import get_git_commit_short

SERVER_BUILD_HEADER = "X-PostHog-Build"
CLIENT_BUILD_HEADER = "X-PostHog-Client-Build"

CLIENT_BUILD_PATTERN = re.compile(r"[0-9a-f]{7,40}")

API_REQUESTS_BY_CLIENT_BUILD = Counter(
    "posthog_api_requests_by_client_build",
    "API requests that carry the frontend build, by whether it matches the server build and by response status class.",
    ["builds", "status_class"],
)


def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def valid_client_build(value: str | None) -> str | None:
    if not value or not CLIENT_BUILD_PATTERN.fullmatch(value):
        return None
    return value


class ClientBuildSkewMiddleware:
    """Tags API responses with the server build and counts requests from a frontend on another build."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        is_api_request = request.path.startswith("/api/")
        response = self.get_response(request)
        if not is_api_request:
            return response

        server_build = get_git_commit_short()
        if not server_build:
            return response
        response[SERVER_BUILD_HEADER] = server_build

        client_build = valid_client_build(request.headers.get(CLIENT_BUILD_HEADER))
        if not client_build:
            return response
        builds = "same" if client_build == server_build else "different"
        API_REQUESTS_BY_CLIENT_BUILD.labels(builds=builds, status_class=status_class(response.status_code)).inc()
        return response
