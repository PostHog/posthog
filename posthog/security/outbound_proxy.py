"""Outbound CONNECT proxy helpers for external HTTP requests.

Drop-in replacements for `requests`, `httpx`, and `aiohttp` that
automatically route traffic through the outbound proxy when enabled.
Import them instead of the bare libraries for any call to a public or
user-controlled URL:

    from posthog.security.outbound_proxy import external_requests
    external_requests.get("https://api.example.com/data")

    from posthog.security.outbound_proxy import external_httpx
    external_httpx.get("https://api.example.com/data")

    from posthog.security.outbound_proxy import external_httpx_client
    with external_httpx_client() as client:
        client.get("https://api.example.com/data")

    from posthog.security.outbound_proxy import external_aiohttp_session
    async with external_aiohttp_session() as session:
        async with session.get("https://api.example.com/data") as resp: ...

Internal service-to-service calls should keep using the plain libraries.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

import requests


def get_proxy_config() -> dict[str, str] | None:
    """Return proxy dict for requests if the outbound CONNECT proxy is enabled."""
    if settings.OUTBOUND_PROXY_ENABLED and settings.OUTBOUND_PROXY_URL:
        return {
            "http": settings.OUTBOUND_PROXY_URL,
            "https": settings.OUTBOUND_PROXY_URL,
        }
    return None


def get_proxy_url() -> str | None:
    """Return the raw proxy URL string if enabled, else None."""
    if settings.OUTBOUND_PROXY_ENABLED and settings.OUTBOUND_PROXY_URL:
        return settings.OUTBOUND_PROXY_URL
    return None


# ---------------------------------------------------------------------------
# requests — pre-configured Session instance
# ---------------------------------------------------------------------------


def external_requests_session() -> requests.Session:
    session = requests.Session()
    cfg = get_proxy_config()
    if cfg:
        session.proxies.update(cfg)
    return session


external_requests: requests.Session = external_requests_session()


# ---------------------------------------------------------------------------
# httpx — lazy-initialized Client instance
# ---------------------------------------------------------------------------


class _LazyExternalHttpx:
    """Lazy proxy around ``httpx.Client`` so we don't import httpx at module load."""

    _client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            proxy_url = get_proxy_url()
            self._client = httpx.Client(proxy=proxy_url) if proxy_url else httpx.Client()
        return self._client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_client(), name)


external_httpx: Any = _LazyExternalHttpx()


def external_httpx_client(**kwargs: Any) -> Any:
    """Create a new ``httpx.Client`` that routes through the proxy.

    Use this when you need a context-managed client with a distinct lifecycle
    (e.g. connection pooling scoped to a task).  For simple one-off calls,
    ``external_httpx.get(...)`` is sufficient.

    Usage::

        with external_httpx_client() as client:
            resp = client.get("https://api.example.com/data")
    """
    import httpx

    proxy_url = get_proxy_url()
    return httpx.Client(proxy=proxy_url, **kwargs) if proxy_url else httpx.Client(**kwargs)


# ---------------------------------------------------------------------------
# aiohttp — session factory (no session-level proxy support, needs wrapper)
# ---------------------------------------------------------------------------


def external_aiohttp_session(**kwargs: Any) -> Any:
    """Create an ``aiohttp.ClientSession`` that routes through the proxy.

    Usage::

        async with external_aiohttp_session() as session:
            async with session.get(url) as resp:
                data = await resp.json()
    """
    import aiohttp

    proxy_url = get_proxy_url()
    if proxy_url:
        return _ProxiedAiohttpSession(proxy_url=proxy_url, **kwargs)
    return aiohttp.ClientSession(**kwargs)


class _ProxiedAiohttpSession:
    """Wraps ``aiohttp.ClientSession`` to inject the proxy URL into every request."""

    def __init__(self, proxy_url: str, **session_kwargs: Any) -> None:
        import aiohttp

        self._proxy_url = proxy_url
        self._session = aiohttp.ClientSession(**session_kwargs)

    async def __aenter__(self) -> _ProxiedAiohttpSession:
        await self._session.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._session.__aexit__(*args)

    async def close(self) -> None:
        await self._session.close()

    def _inject(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if "proxy" not in kwargs:
            kwargs["proxy"] = self._proxy_url
        return kwargs

    def get(self, url: Any, **kwargs: Any) -> Any:
        return self._session.get(url, **self._inject(kwargs))

    def post(self, url: Any, **kwargs: Any) -> Any:
        return self._session.post(url, **self._inject(kwargs))

    def put(self, url: Any, **kwargs: Any) -> Any:
        return self._session.put(url, **self._inject(kwargs))

    def patch(self, url: Any, **kwargs: Any) -> Any:
        return self._session.patch(url, **self._inject(kwargs))

    def delete(self, url: Any, **kwargs: Any) -> Any:
        return self._session.delete(url, **self._inject(kwargs))

    def head(self, url: Any, **kwargs: Any) -> Any:
        return self._session.head(url, **self._inject(kwargs))

    def options(self, url: Any, **kwargs: Any) -> Any:
        return self._session.options(url, **self._inject(kwargs))

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        return self._session.request(method, url, **self._inject(kwargs))
