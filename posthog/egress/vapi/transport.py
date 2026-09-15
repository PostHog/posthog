"""Recorded transport for calls to the Vapi API.

Vapi documents no REST request limit. The limit it does enforce is concurrent call slots, which a
request-rate budget cannot model, so these calls are recorded but not gated. The caller maps Vapi's
own 429 to a retryable error.
"""

from typing import Any

import requests

from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.transport.transport import RecordedEgressClient
from posthog.egress.vapi.observability import vapi_egress


class VapiClient(RecordedEgressClient):
    observability = vapi_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}


_vapi_client = VapiClient()


def vapi_request(
    method: str,
    url: str,
    *,
    api_token: str,
    source: str,
    endpoint: str,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    return _vapi_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_token}"},
        scope=scope_fingerprint(api_token),
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
