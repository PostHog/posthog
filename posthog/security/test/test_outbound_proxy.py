import pytest

import httpx
import requests
import requests_mock as rm

from posthog.security.outbound_proxy import (
    internal_httpx_async_client,
    internal_httpx_client,
    internal_requests,
    internal_requests_session,
)

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
    client = internal_httpx_client()
    assert isinstance(client._transport, httpx.HTTPTransport)
    client.close()


def test_internal_httpx_client_passes_kwargs():
    client = internal_httpx_client(timeout=5.0)
    assert client.timeout.connect == 5.0
    client.close()


def test_internal_httpx_client_explicit_trust_env_not_overridden():
    client = internal_httpx_client(trust_env=True)
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
