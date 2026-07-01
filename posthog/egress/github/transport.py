"""GitHub incarnation of the egress transport.

``github_request`` is the one way to call GitHub from anywhere in the codebase: it gates on the shared
per-installation budget and records telemetry by construction, so a caller physically can't forget
either. It is *token-agnostic* — pass whatever ``Authorization`` header the caller holds (installation
token, user token, PAT, or PostHog's shared token) and the ``installation_id`` as ``scope`` when known.

This module lives in ``egress`` (not the model layer) and imports nothing from ``posthog.models`` — the
model-coupled ``GitHubIntegrationBase`` is a *consumer* of this, not the other way round. ``GITHUB_API_VERSION``
is defined here for the same reason: the transport needs it, and it can't reach back into ``integration.py``.
"""

import requests

from posthog.egress.github.limiter import consume_github_installation_sync
from posthog.egress.github.observability import record_github_api_exception, record_github_api_response
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient

# The GitHub REST API version we pin every request to. Lives here (not integration.py) so the egress
# layer stays free of any posthog.models import; integration.py imports it back from here.
GITHUB_API_VERSION = "2022-11-28"


class GitHubEgressBudgetExhausted(EgressBudgetExhausted):
    """A deferrable (BATCH/NORMAL) GitHub call was shed by our egress limiter before it was sent.
    Distinct from ``GitHubRateLimitError`` (GitHub itself returned 429) — this is our own budget, so a
    caller that can defer (e.g. the warehouse sync) catches it and backs off."""


class GitHubClient(EgressClient):
    """The GitHub incarnation of :class:`EgressClient`. Stateless and token-agnostic, so one shared
    instance serves every caller; wire it through :func:`github_request`."""

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}

    def _consume(self, scope: str, priority: Priority, source: str) -> bool:
        return consume_github_installation_sync(scope, priority=priority, source=source)

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_github_api_response(response, source=source, installation_id=scope, method=method, endpoint=endpoint)

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_github_api_exception(source=source, installation_id=scope, method=method, url=url, endpoint=endpoint)

    def _budget_exhausted_error(self, scope: str) -> GitHubEgressBudgetExhausted:
        return GitHubEgressBudgetExhausted(f"GitHub egress budget exhausted for installation {scope}; deferring")


# Stateless — one shared instance for the whole process.
_github_client = GitHubClient()


def github_request(
    method: str,
    url: str,
    *,
    source: str,
    headers: dict[str, str] | None = None,
    installation_id: str | None = None,
    priority: Priority = Priority.CRITICAL,
    endpoint: str | None = None,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs,
) -> requests.Response:
    """Make a gated, recorded GitHub API request. ``installation_id`` is the shared budget owner — pass
    it when known so the call is gated (at ``priority``) and the rate-limit gauges are set; leave it
    ``None`` for identity-blind callers (raw PATs, PostHog's public token), which record volume only.
    ``source`` attributes the call to a subsystem. ``headers`` must carry the caller's ``Authorization``."""
    return _github_client.request(
        method,
        url,
        source=source,
        headers=headers,
        scope=installation_id,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
