import time
from typing import TypedDict
from urllib.parse import urlparse

import requests

from posthog.egress.limiter.policies import Priority
from posthog.egress.public_web.limiter import consume_public_web_sync
from posthog.egress.public_web.observability import record_public_web_exception, record_public_web_response
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session


class PublicWebFetchError(Exception):
    pass


class PublicWebResponse(TypedDict):
    status_code: int
    headers: dict[str, str]
    body: bytes
    final_url: str


class PublicWebEgressBudgetExhausted(EgressBudgetExhausted):
    pass


class PublicWebClient(EgressClient):
    def _standard_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": "PostHog-PublicWeb/1.0 (+https://posthog.com)",
        }

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_public_web_sync(scope, priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_public_web_response(response, source=source, method=method, endpoint=endpoint or "unknown")

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_public_web_exception(source=source, method=method, endpoint=endpoint or "unknown", url=url)

    def _budget_exhausted_error(self, scope: str) -> PublicWebEgressBudgetExhausted:
        return PublicWebEgressBudgetExhausted("Public-web request budget exhausted")


_public_web_client = PublicWebClient()


def public_web_get(
    url: str,
    *,
    source: str,
    endpoint: str,
    max_bytes: int,
    timeout: tuple[float, float] = (3.0, 5.0),
    max_duration_seconds: float = 10.0,
) -> PublicWebResponse:
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        _ = parsed.port
    except ValueError as error:
        raise PublicWebFetchError("The site URL is invalid.") from error
    if parsed.scheme.lower() not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise PublicWebFetchError("The site URL is invalid.")
    if max_bytes < 1:
        raise PublicWebFetchError("The response size limit must be positive.")
    if max_duration_seconds <= 0:
        raise PublicWebFetchError("The public-web request deadline has expired.")

    deadline = time.monotonic() + max_duration_seconds

    def remaining_seconds() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PublicWebFetchError("The public-web request deadline has expired.")
        return remaining

    try:
        with pinned_session(url) as session:
            request_budget = remaining_seconds()
            response = _public_web_client.request(
                "GET",
                url,
                source=source,
                scope=hostname,
                priority=Priority.NORMAL,
                endpoint=endpoint,
                timeout=(min(timeout[0], request_budget), min(timeout[1], request_budget)),
                session=session,
                allow_redirects=False,
                stream=True,
            )
            try:
                remaining_seconds()
                declared_size = response.headers.get("Content-Length")
                if declared_size and declared_size.isdigit() and int(declared_size) > max_bytes:
                    raise PublicWebFetchError("The site response is too large to inspect.")

                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    remaining_seconds()
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise PublicWebFetchError("The site response is too large to inspect.")
                    chunks.append(chunk)
                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": b"".join(chunks),
                    "final_url": url,
                }
            finally:
                response.close()
    except (requests.RequestException, SSRFBlockedError, PublicWebEgressBudgetExhausted) as error:
        raise PublicWebFetchError("The site could not be inspected safely.") from error
