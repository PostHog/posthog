"""Recorded transport for the public npm registry.

The registry publishes no request limit a rate budget can model, so these calls are recorded but not
gated. Requests are anonymous: no credential is sent, so there is no account identity to budget.
"""

from typing import Any
from urllib.parse import quote

import requests

from posthog.egress.npm_registry.observability import npm_registry_egress
from posthog.egress.transport.transport import RecordedEgressClient

NPM_REGISTRY_URL = "https://registry.npmjs.org"


class NpmRegistryClient(RecordedEgressClient):
    observability = npm_registry_egress
    egress_domain = "npm_registry"

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}


_npm_registry_client = NpmRegistryClient()


def npm_packument_url(package_name: str) -> str:
    # A scoped name keeps its leading "@" and encodes the "/" between scope and name.
    return f"{NPM_REGISTRY_URL}/{quote(package_name, safe='@')}"


def npm_registry_request(
    method: str,
    url: str,
    *,
    source: str,
    endpoint: str,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    return _npm_registry_client.request(
        method,
        url,
        source=source,
        scope="public",
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
