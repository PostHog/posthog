"""Outbound proxy helpers for HTTP requests.

External calls use the standard library defaults — ``requests``,
``httpx``, and ``aiohttp`` all honour ``HTTP_PROXY`` / ``HTTPS_PROXY``
env vars automatically (``trust_env=True`` is the default for
``requests`` and ``httpx``; ``aiohttp`` needs it set explicitly).

Internal service-to-service calls should use the ``internal_*`` helpers
from this module, which explicitly bypass env proxy vars:

    from posthog.security.outbound_proxy import internal_requests_session
    session = internal_requests_session()
    session.get("http://plugin-server:6738/status")

    from posthog.security.outbound_proxy import internal_httpx_client
    with internal_httpx_client() as client:
        client.post("http://chromium-service:3020/screenshot", json=payload)
"""

from __future__ import annotations

from typing import Any

import requests

# ---------------------------------------------------------------------------
# Internal helpers — bypass HTTP_PROXY / HTTPS_PROXY env vars
# ---------------------------------------------------------------------------


def internal_requests_session() -> requests.Session:
    """Create a requests.Session that explicitly bypasses env proxy vars.

    Use for internal service-to-service calls that must not go through
    HTTP_PROXY/HTTPS_PROXY.
    """
    session = requests.Session()
    session.trust_env = False
    return session


internal_requests: requests.Session = internal_requests_session()


def internal_httpx_client(**kwargs: Any) -> Any:
    """Create an ``httpx.Client`` that bypasses env proxy vars."""
    import httpx

    kwargs.setdefault("trust_env", False)
    return httpx.Client(**kwargs)


def internal_httpx_async_client(**kwargs: Any) -> Any:
    """Create an ``httpx.AsyncClient`` that bypasses env proxy vars."""
    import httpx

    kwargs.setdefault("trust_env", False)
    return httpx.AsyncClient(**kwargs)
