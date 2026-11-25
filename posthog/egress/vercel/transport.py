"""Recorded transport for the Vercel REST API.

``vercel_request`` is the one way to call Vercel from anywhere in the codebase. It records every call
under the Vercel installation it acts for, and stays token-agnostic: the caller sends its own
``Authorization`` header, or a session that carries it.
"""

import requests

from posthog.egress.transport.transport import RecordedEgressClient
from posthog.egress.vercel.observability import vercel_egress


class VercelClient(RecordedEgressClient):
    observability = vercel_egress
    egress_domain = "vercel"


_vercel_client = VercelClient()


def vercel_request(
    method: str,
    url: str,
    *,
    source: str,
    installation_id: str | None,
    endpoint: str | None = None,
    headers: dict[str, str] | None = None,
    data: str | bytes | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    """Make a recorded Vercel request. ``installation_id`` is the Vercel installation (``icfg_...``) the
    call acts for, or None for a call made before PostHog knows it, such as an OAuth code exchange.
    Pass ``endpoint`` when the path comes from a caller, so the label stays bounded.
    ``data`` is the encoded request body."""
    return _vercel_client.request(
        method,
        url,
        source=source,
        headers=headers,
        scope=installation_id,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        data=data,
        auth=auth,
    )
