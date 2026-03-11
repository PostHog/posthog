import pytest

import httpx
import requests
import requests_mock as rm

from posthog.security.outbound_proxy import (
    external_aiohttp_session,
    external_httpx_client,
    external_requests,
    external_requests_session,
    get_proxy_config,
    get_proxy_url,
    internal_httpx_async_client,
    internal_httpx_client,
    internal_requests,
    internal_requests_session,
)


@pytest.mark.parametrize(
    "enabled,url,expected",
    [
        (True, "http://proxy:8080", {"http": "http://proxy:8080", "https": "http://proxy:8080"}),
        (False, "http://proxy:8080", None),
        (True, "", None),
        (False, "", None),
    ],
    ids=["enabled-with-url", "disabled-with-url", "enabled-no-url", "disabled-no-url"],
)
def test_get_proxy_config(enabled, url, expected, settings):
    settings.OUTBOUND_PROXY_ENABLED = enabled
    settings.OUTBOUND_PROXY_URL = url
    assert get_proxy_config() == expected


@pytest.mark.parametrize(
    "enabled,url,expected",
    [
        (True, "http://proxy:8080", "http://proxy:8080"),
        (False, "http://proxy:8080", None),
        (True, "", None),
    ],
    ids=["enabled", "disabled", "no-url"],
)
def test_get_proxy_url(enabled, url, expected, settings):
    settings.OUTBOUND_PROXY_ENABLED = enabled
    settings.OUTBOUND_PROXY_URL = url
    assert get_proxy_url() == expected


@pytest.mark.parametrize(
    "enabled,url",
    [
        (True, "http://proxy:8080"),
        (False, ""),
    ],
    ids=["proxy-enabled", "proxy-disabled"],
)
def test_make_proxied_session(enabled, url, settings):
    settings.OUTBOUND_PROXY_ENABLED = enabled
    settings.OUTBOUND_PROXY_URL = url
    session = external_requests_session()
    if enabled and url:
        assert session.proxies["http"] == url
        assert session.proxies["https"] == url
    else:
        assert "http" not in session.proxies or session.proxies.get("http") == ""


def test_external_requests_is_a_session():
    assert isinstance(external_requests, __import__("requests").Session)


@pytest.mark.parametrize(
    "method",
    ["get", "post", "put", "patch", "delete", "head", "options", "request"],
)
def test_external_requests_methods_work(method):
    with rm.Mocker() as m:
        m.register_uri(rm.ANY, "http://example.com/test", json={"ok": True})
        func = getattr(external_requests, method)
        if method == "request":
            resp = func("GET", "http://example.com/test")
        else:
            resp = func("http://example.com/test")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_external_aiohttp_session_no_proxy(settings):
    settings.OUTBOUND_PROXY_ENABLED = False
    settings.OUTBOUND_PROXY_URL = ""
    import aiohttp

    session = external_aiohttp_session()
    assert isinstance(session, aiohttp.ClientSession)
    await session.close()


@pytest.mark.asyncio
async def test_external_aiohttp_session_with_proxy(settings):
    settings.OUTBOUND_PROXY_ENABLED = True
    settings.OUTBOUND_PROXY_URL = "http://proxy:8080"
    from posthog.security.outbound_proxy import _ProxiedAiohttpSession

    session = external_aiohttp_session()
    assert isinstance(session, _ProxiedAiohttpSession)
    await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attr",
    ["closed", "cookie_jar", "headers"],
    ids=["closed", "cookie_jar", "headers"],
)
async def test_proxied_aiohttp_session_delegates_attributes(attr, settings):
    settings.OUTBOUND_PROXY_ENABLED = True
    settings.OUTBOUND_PROXY_URL = "http://proxy:8080"
    session = external_aiohttp_session()
    assert getattr(session, attr) == getattr(session._session, attr)
    await session.close()


@pytest.mark.asyncio
async def test_proxied_aiohttp_session_closed_reflects_state(settings):
    settings.OUTBOUND_PROXY_ENABLED = True
    settings.OUTBOUND_PROXY_URL = "http://proxy:8080"
    session = external_aiohttp_session()
    assert session.closed is False
    await session.close()
    assert session.closed is True


@pytest.mark.asyncio
async def test_proxied_aiohttp_session_aenter_returns_self(settings):
    settings.OUTBOUND_PROXY_ENABLED = True
    settings.OUTBOUND_PROXY_URL = "http://proxy:8080"
    from posthog.security.outbound_proxy import _ProxiedAiohttpSession

    session = external_aiohttp_session()
    entered = await session.__aenter__()
    assert entered is session
    assert isinstance(entered, _ProxiedAiohttpSession)
    await session.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_proxied_aiohttp_session_nonexistent_attr_raises(settings):
    settings.OUTBOUND_PROXY_ENABLED = True
    settings.OUTBOUND_PROXY_URL = "http://proxy:8080"
    session = external_aiohttp_session()
    with pytest.raises(AttributeError):
        _ = session.this_attribute_does_not_exist
    await session.close()


# ---------------------------------------------------------------------------
# external_* passthrough — no proxy configured behaves like bare libraries
# ---------------------------------------------------------------------------


def test_external_requests_session_no_proxy_is_plain_session(settings):
    settings.OUTBOUND_PROXY_ENABLED = False
    settings.OUTBOUND_PROXY_URL = ""
    session = external_requests_session()
    assert isinstance(session, requests.Session)
    assert session.trust_env is True
    assert session.proxies.get("http") in (None, "")
    assert session.proxies.get("https") in (None, "")


def test_external_requests_session_no_proxy_methods_work(settings):
    settings.OUTBOUND_PROXY_ENABLED = False
    settings.OUTBOUND_PROXY_URL = ""
    session = external_requests_session()
    with rm.Mocker() as m:
        m.register_uri(rm.ANY, "https://api.example.com/data", json={"ok": True})
        resp = session.get("https://api.example.com/data")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


def test_external_httpx_client_no_proxy_returns_plain_client(settings):
    settings.OUTBOUND_PROXY_ENABLED = False
    settings.OUTBOUND_PROXY_URL = ""
    client = external_httpx_client()
    assert isinstance(client, httpx.Client)
    assert isinstance(client._transport, httpx.HTTPTransport)
    client.close()


def test_external_httpx_client_no_proxy_passes_kwargs(settings):
    settings.OUTBOUND_PROXY_ENABLED = False
    settings.OUTBOUND_PROXY_URL = ""
    client = external_httpx_client(timeout=7.0)
    assert isinstance(client, httpx.Client)
    assert client.timeout.connect == 7.0
    client.close()


@pytest.mark.asyncio
async def test_external_aiohttp_session_no_proxy_passes_kwargs(settings):
    settings.OUTBOUND_PROXY_ENABLED = False
    settings.OUTBOUND_PROXY_URL = ""
    import aiohttp

    session = external_aiohttp_session(headers={"X-Custom": "value"})
    assert isinstance(session, aiohttp.ClientSession)
    assert session.headers.get("X-Custom") == "value"
    await session.close()


# ---------------------------------------------------------------------------
# internal_requests_session
# ---------------------------------------------------------------------------


def test_internal_requests_session_trust_env_false():
    session = internal_requests_session()
    assert session.trust_env is False


def test_internal_requests_session_ignores_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://should-not-be-used:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://should-not-be-used:9999")
    session = internal_requests_session()
    assert session.trust_env is False
    assert session.proxies.get("https") in (None, "")
    assert session.proxies.get("http") in (None, "")


def test_internal_requests_session_returns_new_instance_each_call():
    s1 = internal_requests_session()
    s2 = internal_requests_session()
    assert s1 is not s2


@pytest.mark.parametrize(
    "method",
    ["get", "post", "put", "patch", "delete", "head", "options", "request"],
)
def test_internal_requests_session_methods_work(method):
    session = internal_requests_session()
    with rm.Mocker() as m:
        m.register_uri(rm.ANY, "http://internal-service:8000/test", json={"ok": True})
        func = getattr(session, method)
        if method == "request":
            resp = func("GET", "http://internal-service:8000/test")
        else:
            resp = func("http://internal-service:8000/test")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# internal_requests singleton
# ---------------------------------------------------------------------------


def test_internal_requests_is_a_session():
    assert isinstance(internal_requests, requests.Session)


def test_internal_requests_trust_env_false():
    assert internal_requests.trust_env is False


# ---------------------------------------------------------------------------
# internal_httpx_client
# ---------------------------------------------------------------------------


def test_internal_httpx_client_returns_httpx_client():
    client = internal_httpx_client()
    assert isinstance(client, httpx.Client)
    client.close()


def test_internal_httpx_client_proxy_is_none():
    # When proxy=None is passed, httpx should not wrap the transport in a proxy layer
    client = internal_httpx_client()
    assert isinstance(client._transport, httpx.HTTPTransport)
    client.close()


def test_internal_httpx_client_passes_kwargs():
    client = internal_httpx_client(timeout=5.0)
    assert client.timeout.connect == 5.0
    client.close()


def test_internal_httpx_client_explicit_trust_env_not_overridden():
    client = internal_httpx_client(trust_env=True)
    # setdefault should not clobber an explicitly passed trust_env
    assert client._transport is not None
    client.close()


def test_internal_httpx_client_ignores_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:9999")
    client = internal_httpx_client()
    assert isinstance(client._transport, httpx.HTTPTransport)
    client.close()


# ---------------------------------------------------------------------------
# internal_httpx_async_client
# ---------------------------------------------------------------------------


def test_internal_httpx_async_client_returns_async_client():
    client = internal_httpx_async_client()
    assert isinstance(client, httpx.AsyncClient)


def test_internal_httpx_async_client_proxy_is_none():
    # When proxy=None is passed, httpx should not wrap the transport in a proxy layer
    client = internal_httpx_async_client()
    assert isinstance(client._transport, httpx.AsyncHTTPTransport)


def test_internal_httpx_async_client_passes_kwargs():
    client = internal_httpx_async_client(timeout=10.0)
    assert client.timeout.connect == 10.0


def test_internal_httpx_async_client_ignores_env_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:9999")
    client = internal_httpx_async_client()
    assert isinstance(client._transport, httpx.AsyncHTTPTransport)
