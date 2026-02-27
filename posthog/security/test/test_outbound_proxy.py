import pytest

import requests_mock as rm

from posthog.security.outbound_proxy import (
    external_aiohttp_session,
    external_requests,
    get_proxy_config,
    get_proxy_url,
    make_proxied_requests_session,
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
    session = make_proxied_requests_session()
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
