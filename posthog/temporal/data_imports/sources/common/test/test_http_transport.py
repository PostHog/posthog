import socket

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.sources.common.http.observer import record_blocked_request
from posthog.temporal.data_imports.sources.common.http.transport import (
    DEFAULT_RETRY,
    BlockedHostError,
    SSRFGuardedHTTPAdapter,
    TrackedHTTPAdapter,
    _enforce_peer_ip_safe,
    _SSRFGuardedHTTPSConnection,
    _SSRFGuardedHTTPSConnectionPool,
    _SSRFGuardedPoolManager,
    make_tracked_adapter,
    make_tracked_session,
)


@pytest.fixture
def mock_record():
    with patch("posthog.temporal.data_imports.sources.common.http.transport.record_request") as m:
        yield m


@pytest.fixture
def mock_blocked():
    with patch("posthog.temporal.data_imports.sources.common.http.transport.record_blocked_request") as m:
        yield m


def _fake_response(status_code: int = 200, body: bytes = b"ok") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = body
    resp.headers["Content-Length"] = str(len(body))
    return resp


@pytest.fixture
def fake_http_send():
    """Patch the parent `HTTPAdapter.send` so `TrackedHTTPAdapter.send()`'s `super().send()` returns a canned response without touching the network."""

    def _factory(response: Response):
        return patch.object(HTTPAdapter, "send", return_value=response)

    return _factory


def test_make_tracked_session_mounts_tracked_adapter_for_both_schemes():
    session = make_tracked_session()

    https_adapter = session.get_adapter("https://example.com/")
    http_adapter = session.get_adapter("http://example.com/")

    assert isinstance(https_adapter, TrackedHTTPAdapter)
    assert isinstance(http_adapter, TrackedHTTPAdapter)


def test_make_tracked_session_uses_default_retry():
    session = make_tracked_session()
    adapter = session.get_adapter("https://example.com/")
    assert isinstance(adapter, TrackedHTTPAdapter)

    assert adapter.max_retries.total == DEFAULT_RETRY.total
    assert adapter.max_retries.backoff_factor == DEFAULT_RETRY.backoff_factor
    assert set(adapter.max_retries.status_forcelist or ()) == set(DEFAULT_RETRY.status_forcelist or ())


def test_make_tracked_session_honors_custom_retry():
    custom = Retry(total=7, backoff_factor=2.0, status_forcelist=(418,))
    session = make_tracked_session(retry=custom)
    adapter = session.get_adapter("https://example.com/")
    assert isinstance(adapter, TrackedHTTPAdapter)

    assert adapter.max_retries.total == 7
    assert adapter.max_retries.backoff_factor == 2.0


def test_make_tracked_session_merges_headers():
    session = make_tracked_session(headers={"X-Source": "stripe", "User-Agent": "posthog/test"})

    assert session.headers["X-Source"] == "stripe"
    assert session.headers["User-Agent"] == "posthog/test"


def test_make_tracked_adapter_with_none_retry_uses_default():
    """`retry=None` is the explicit "use default" sentinel — not "disable retries"."""
    adapter = make_tracked_adapter(retry=None)

    # Should equal the DEFAULT_RETRY total
    assert adapter.max_retries.total == DEFAULT_RETRY.total


def test_send_records_request_for_2xx(mock_record, fake_http_send):
    session = make_tracked_session()

    with fake_http_send(_fake_response(status_code=200, body=b"ok")):
        response = session.get("https://api.example.com/v1/ok")

    assert response.status_code == 200
    assert mock_record.call_count == 1
    args, kwargs = mock_record.call_args
    # First positional arg is the PreparedRequest, second is the Response.
    assert args[0].url == "https://api.example.com/v1/ok"
    assert args[1].status_code == 200
    assert kwargs["exception"] is None
    assert "started_at_monotonic" in kwargs


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 502, 503])
def test_send_records_request_for_non_2xx(mock_record, fake_http_send, status_code):
    session = make_tracked_session(retry=Retry(total=0))

    with fake_http_send(_fake_response(status_code=status_code, body=b"err")):
        response = session.get("https://api.example.com/v1/err")

    assert response.status_code == status_code
    assert mock_record.call_count == 1
    response_arg = mock_record.call_args.args[1]
    assert response_arg.status_code == status_code


def test_send_records_request_on_connection_exception(mock_record):
    """Network errors must still call record_request, and the exception must propagate."""
    session = make_tracked_session(retry=Retry(total=0))
    with pytest.raises(requests.exceptions.RequestException):
        # 127.0.0.1:1 is reserved/never-listening; resolves instantly with a connection refused.
        session.get("http://127.0.0.1:1/", timeout=2)

    assert mock_record.call_count == 1
    request_arg = mock_record.call_args.args[0]
    response_arg = mock_record.call_args.args[1]
    assert request_arg.url == "http://127.0.0.1:1/"
    assert response_arg is None
    assert mock_record.call_args.kwargs["exception"] is not None


def test_send_does_not_mask_real_outcome_when_record_raises(fake_http_send):
    """If record_request itself raises, the response must still be returned to the caller."""
    session = make_tracked_session()

    with (
        fake_http_send(_fake_response(status_code=200, body=b"ok")),
        patch(
            "posthog.temporal.data_imports.sources.common.http.transport.record_request",
            side_effect=RuntimeError("observer broken"),
        ),
    ):
        # No exception should bubble up; the swallow happens inside `TrackedHTTPAdapter.send`'s `finally`.
        response = session.get("https://api.example.com/")

    assert response.status_code == 200


def test_send_does_not_mask_real_exception_when_record_raises():
    """If both the request fails AND the observer raises, the original exception must propagate."""
    session = make_tracked_session(retry=Retry(total=0))

    with patch(
        "posthog.temporal.data_imports.sources.common.http.transport.record_request",
        side_effect=RuntimeError("observer broken"),
    ):
        with pytest.raises(requests.exceptions.RequestException):
            session.get("http://127.0.0.1:1/", timeout=2)


def test_make_tracked_session_is_ssrf_guarded_by_default():
    """The factory mounts the SSRF guard unless `allow_internal_ips` opts out."""
    session = make_tracked_session()

    https_adapter = session.get_adapter("https://example.com/")
    http_adapter = session.get_adapter("http://example.com/")

    assert isinstance(https_adapter, SSRFGuardedHTTPAdapter)
    assert isinstance(http_adapter, SSRFGuardedHTTPAdapter)


@pytest.mark.parametrize("team_id", [None, 42])
def test_make_tracked_session_carries_team_id_onto_the_guard(team_id):
    """team_id reaches the guard as the allowlist team; None means no exemption."""
    session = make_tracked_session(team_id=team_id)
    adapter = session.get_adapter("https://example.com/")

    assert isinstance(adapter, SSRFGuardedHTTPAdapter)
    assert adapter._team_id == team_id


@pytest.mark.parametrize("factory_kwargs", [{}, {"team_id": 42}])
def test_allow_internal_ips_opts_out_of_the_guard(factory_kwargs):
    """`allow_internal_ips=True` yields a plain TrackedHTTPAdapter — no SSRF guard."""
    session = make_tracked_session(allow_internal_ips=True, **factory_kwargs)
    adapter = session.get_adapter("https://example.com/")
    assert type(adapter) is TrackedHTTPAdapter


def test_make_tracked_adapter_opt_out_returns_plain_adapter():
    assert type(make_tracked_adapter(allow_internal_ips=True)) is TrackedHTTPAdapter
    assert isinstance(make_tracked_adapter(), SSRFGuardedHTTPAdapter)


@pytest.mark.parametrize("factory_kwargs", [{}, {"allow_internal_ips": True}])
def test_make_tracked_session_disables_proxy_env(factory_kwargs):
    """trust_env=False — HTTP(S)_PROXY env vars must not route around the guard."""
    assert make_tracked_session(**factory_kwargs).trust_env is False


def test_ssrf_guard_blocks_unsafe_host(mock_record, mock_blocked):
    """When `_is_host_safe` rejects the host, `send()` raises before the
    request goes out. Per-host classification — private ranges, the IMDS
    address, etc. — is `_is_host_safe`'s job and is covered for real in
    test_mixins.py; here it is stubbed, so this asserts only the wiring."""
    adapter = SSRFGuardedHTTPAdapter(team_id=42)
    prepared = requests.Request("GET", "https://internal.example.com/data").prepare()

    with patch(
        "posthog.temporal.data_imports.sources.common.http.transport._is_host_safe",
        return_value=(False, "Hosts with internal IP addresses are not allowed"),
    ):
        with pytest.raises(BlockedHostError, match="internal IP"):
            adapter.send(prepared)

    # A blocked request never reaches the network, so the observer never sees it.
    mock_record.assert_not_called()
    # ...but the block itself must be logged for Grafana visibility.
    mock_blocked.assert_called_once()
    assert mock_blocked.call_args.kwargs["layer"] == "preflight"
    assert mock_blocked.call_args.kwargs["team_id"] == 42


def test_ssrf_guard_blocks_url_without_hostname(mock_record, mock_blocked):
    adapter = SSRFGuardedHTTPAdapter(team_id=42)
    prepared = requests.Request("GET", "https://api.example.com/").prepare()
    prepared.url = "/relative/path"  # a URL with no host must not slip past the guard

    with pytest.raises(BlockedHostError, match="missing a hostname"):
        adapter.send(prepared)

    mock_record.assert_not_called()
    mock_blocked.assert_called_once()
    assert mock_blocked.call_args.kwargs["layer"] == "preflight"


def test_ssrf_guard_allows_safe_host(mock_record, fake_http_send):
    adapter = SSRFGuardedHTTPAdapter(team_id=42)
    prepared = requests.Request("GET", "https://api.example.com/data").prepare()

    with (
        patch(
            "posthog.temporal.data_imports.sources.common.http.transport._is_host_safe",
            return_value=(True, None),
        ),
        fake_http_send(_fake_response(status_code=200, body=b"ok")),
    ):
        response = adapter.send(prepared)

    assert response.status_code == 200
    mock_record.assert_called_once()


def test_redirect_to_internal_host_is_blocked(mock_record):
    """A 3xx Location pointing at an internal host is re-vetted: the guard runs
    on the redirect target, not just the original request URL. `requests`
    drives redirects itself (urllib3 gets redirect=False), so each hop is a
    fresh adapter.send() — this is also the mechanism pagination relies on."""
    session = make_tracked_session()

    redirect = _fake_response(status_code=302)
    redirect.headers["Location"] = "http://10.0.0.1/"
    redirect.url = "https://api.example.com/start"
    redirect._content_consumed = True  # no socket to drain

    def _is_safe(host, team_id, **kwargs):
        return (False, "internal address") if host == "10.0.0.1" else (True, None)

    with (
        patch.object(HTTPAdapter, "send", return_value=redirect),
        patch(
            "posthog.temporal.data_imports.sources.common.http.transport._is_host_safe",
            side_effect=_is_safe,
        ),
    ):
        with pytest.raises(BlockedHostError, match="10.0.0.1"):
            session.get("https://api.example.com/start")


# --- Post-connect peer-IP check (DNS-rebinding defense) ---


def test_enforce_peer_ip_safe_rejects_missing_socket():
    with pytest.raises(BlockedHostError, match="no socket"):
        _enforce_peer_ip_safe("example.com", None, team_id=42)


def test_enforce_peer_ip_safe_rejects_unconnected_socket():
    """An unconnected socket has no peer — fail closed rather than skip the check."""
    with socket.socket() as sock:
        with pytest.raises(BlockedHostError, match="Could not determine"):
            _enforce_peer_ip_safe("example.com", sock, team_id=42)


def test_guarded_connection_blocks_internal_peer(mock_blocked):
    """connect() re-checks the live socket — an internal peer is blocked post-connect,
    even though the hostname that was dialed may have looked safe."""

    def _fake_base_connect(self):
        self.sock = MagicMock()
        self.sock.getpeername.return_value = ("10.0.0.7", 443)

    conn = _SSRFGuardedHTTPSConnection("example.com", ssrf_team_id=42)
    with (
        patch.object(HTTPSConnection, "connect", _fake_base_connect),
        patch(
            "posthog.temporal.data_imports.sources.common.http.transport._is_host_safe",
            return_value=(False, "Hosts with internal IP addresses are not allowed"),
        ) as is_safe,
    ):
        with pytest.raises(BlockedHostError, match="10.0.0.7"):
            conn.connect()

    # The hostname is passed for exemption checks; the actual connected peer
    # IP is what gets vetted — `resolved_ip`, not a re-resolution of the name.
    is_safe.assert_called_once_with("example.com", 42, resolved_ip="10.0.0.7")
    # The block is logged under the postconnect layer for Grafana visibility.
    mock_blocked.assert_called_once()
    assert mock_blocked.call_args.kwargs["layer"] == "postconnect"
    assert mock_blocked.call_args.kwargs["team_id"] == 42


def test_guarded_connection_allows_public_peer():
    def _fake_base_connect(self):
        self.sock = MagicMock()
        self.sock.getpeername.return_value = ("203.0.113.10", 443)

    conn = _SSRFGuardedHTTPSConnection("example.com", ssrf_team_id=42)
    with (
        patch.object(HTTPSConnection, "connect", _fake_base_connect),
        patch(
            "posthog.temporal.data_imports.sources.common.http.transport._is_host_safe",
            return_value=(True, None),
        ),
    ):
        conn.connect()  # must not raise


def test_record_blocked_request_never_raises():
    """Block telemetry must never turn a block into a different failure — if it
    raised, the BlockedHostError after it would never be reached."""
    with patch(
        "posthog.temporal.data_imports.sources.common.http.observer.current_job_context",
        side_effect=RuntimeError("context broke"),
    ):
        record_blocked_request(host="example.com", team_id=1, reason="reason", layer="preflight")


@pytest.mark.parametrize("team_id", [None, 77])
def test_session_pool_manager_opens_peer_checking_connections(team_id):
    """team_id rides urllib3's conn_kw down to the connection that opens sockets."""
    session = make_tracked_session(team_id=team_id)
    adapter = session.get_adapter("https://example.com/")

    assert isinstance(adapter.poolmanager, _SSRFGuardedPoolManager)

    pool = adapter.poolmanager.connection_from_url("https://example.com/")
    assert isinstance(pool, _SSRFGuardedHTTPSConnectionPool)

    conn = pool._new_conn()
    assert isinstance(conn, _SSRFGuardedHTTPSConnection)
    assert conn._ssrf_team_id == team_id
