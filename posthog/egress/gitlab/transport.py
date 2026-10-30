"""Recorded transport for GitLab REST API calls, on gitlab.com and on self-managed instances."""

from typing import Any
from urllib.parse import urlsplit

import requests

from posthog.egress.gitlab.observability import gitlab_egress
from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.transport.transport import RecordedEgressClient


def token_scope(url: str, token: str) -> str:
    """GitLab meters each authenticated user on each instance, and a token belongs to one user.
    Host and token are hashed together because the token is a secret and the scope is a metric label."""
    return scope_fingerprint(urlsplit(url).hostname or "", token)


class GitLabClient(RecordedEgressClient):
    """Recorded, never gated. The customer owns the token, and each instance admin sets its own
    limits, so PostHog has no budget it can model. Callers honor a 429 and its Retry-After."""

    observability = gitlab_egress
    egress_domain = "gitlab"

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}


_gitlab_client = GitLabClient()


def gitlab_request(
    method: str,
    url: str,
    *,
    token: str,
    source: str,
    endpoint: str,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """``endpoint`` is a template such as ``/projects/{id}/issues``. Project paths in a URL are
    customer data, so the raw URL never becomes the label."""
    return _gitlab_client.request(
        method,
        url,
        source=source,
        headers={"PRIVATE-TOKEN": token},
        scope=token_scope(url, token),
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
