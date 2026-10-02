"""Recorded transport for the OpenAI auth server that issues ChatGPT OAuth tokens.

OpenAI publishes no request limit for its OAuth token endpoint, so these calls are recorded but not
gated. A refresh token is single use, so a caller never retries a refresh on its own; it reports the
failure and lets the user reconnect.
"""

from typing import Any

import requests

from posthog.egress.openai_auth.observability import openai_auth_egress
from posthog.egress.transport.transport import RecordedEgressClient

OPENAI_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_OAUTH_REVOKE_URL = "https://auth.openai.com/oauth/revoke"


class OpenAIAuthClient(RecordedEgressClient):
    observability = openai_auth_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}


_openai_auth_client = OpenAIAuthClient()


def openai_auth_request(
    method: str,
    url: str,
    *,
    source: str,
    endpoint: str,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    # Every call goes out under the one Codex OAuth client id, so the identity is constant.
    return _openai_auth_client.request(
        method,
        url,
        source=source,
        scope="codex-client",
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
