"""Tracked `requests.Session` factory.

`make_tracked_session(...)` returns a `requests.Session` whose adapters
intercept every dispatched request to feed the observer. Vendor SDKs that
accept a `requests.Session` (Stripe via `stripe.RequestsClient`, gspread,
hubspot-api-client, etc.) can be handed the result of this factory.

The intercept point is the adapter's `send()` rather than a `Session`
subclass, because some SDKs construct their own `Session` and we still
want the metering — they only need to mount the tracked adapter:

    session.mount("https://", make_tracked_adapter(...))

Adapters are SSRF-guarded by default — see `SSRFGuardedHTTPAdapter` for the
two-layer host check; `make_tracked_adapter(allow_internal_ips=True)` opts out.
"""

from __future__ import annotations

import time
import socket
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import requests
from requests import PreparedRequest, Response
from requests.adapters import DEFAULT_POOLBLOCK, HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import PoolManager
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.host_safety import _is_host_safe
from posthog.temporal.data_imports.sources.common.http.observer import record_blocked_request, record_request

DEFAULT_RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    raise_on_status=False,
)


class TrackedHTTPAdapter(HTTPAdapter):
    """`HTTPAdapter` that records every dispatched request via the observer.

    `send()` is the lowest synchronous hook in the requests stack — it sees
    the fully-prepared request and the raw response, exception or not, with
    no SDK-specific framing on top.
    """

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        started = time.monotonic()
        response: Response | None = None
        exception: BaseException | None = None
        try:
            response = super().send(
                request,
                stream=stream,
                timeout=timeout,
                verify=verify,
                cert=cert,
                proxies=proxies,
            )
            return response
        except BaseException as exc:
            exception = exc
            raise
        finally:
            try:
                record_request(
                    request,
                    response,
                    started_at_monotonic=started,
                    exception=exception,
                )
            except Exception:
                # Belt-and-braces: record_request should never raise, but if
                # something does we never want to mask the real outcome.
                pass


class BlockedHostError(Exception):
    """Raised when a request targets — or connects to — an internal host.

    Deliberately a plain `Exception` rather than a `requests.RequestException`
    (which is an `OSError`). The post-connect check raises this from inside
    urllib3's `connect()`, and urllib3 treats an `OSError` there as a
    retryable connection failure — it would be caught, retried, and finally
    re-wrapped as a generic `ConnectionError`. A plain `Exception` propagates
    straight out: a policy denial is not a transient network error and must
    not be retried or have its message buried.
    """


def _enforce_peer_ip_safe(hostname: str, sock: socket.socket | None, team_id: int | None) -> None:
    """Block the connection if the socket's actual peer IP is internal/private.

    Called from a connection's `connect()` — *after* the socket is open — so
    it vets the IP urllib3 genuinely connected to. A rebinding resolver can
    answer "public" when a name is first resolved and "private" when it is
    resolved again to connect, but it cannot change the IP of a socket that
    is already open. `hostname` is passed through so hostname-based
    exemptions (`.postwh.com`) and the team allowlist still apply.
    """
    if sock is None:
        record_blocked_request(
            host=hostname, team_id=team_id, reason="connection has no socket to validate", layer="postconnect"
        )
        raise BlockedHostError("Connection has no socket to validate against")
    try:
        peer_ip = str(sock.getpeername()[0])
    except (OSError, IndexError) as exc:
        record_blocked_request(
            host=hostname, team_id=team_id, reason=f"could not determine peer address: {exc}", layer="postconnect"
        )
        raise BlockedHostError(f"Could not determine the connected peer address: {exc}") from exc
    ok, _err = _is_host_safe(hostname, team_id, resolved_ip=peer_ip)
    if not ok:
        record_blocked_request(
            host=hostname,
            team_id=team_id,
            reason=f"connected peer {peer_ip} is an internal address",
            layer="postconnect",
        )
        raise BlockedHostError(f"Blocked connection to {hostname!r}: peer {peer_ip!r} is an internal address")


class _SSRFGuardedHTTPConnection(HTTPConnection):
    """`HTTPConnection` that re-checks the peer IP once the socket is open."""

    def __init__(self, *args: Any, ssrf_team_id: int | None = None, **kwargs: Any) -> None:
        self._ssrf_team_id = ssrf_team_id
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        super().connect()
        _enforce_peer_ip_safe(self.host, self.sock, self._ssrf_team_id)


class _SSRFGuardedHTTPSConnection(HTTPSConnection):
    """`HTTPSConnection` that re-checks the peer IP once the socket is open.

    The check runs after `super().connect()`, i.e. after the TLS handshake.
    A handshake with an internal host sends no application data, and the
    HTTP request itself is never dispatched — so the SSRF payload never
    reaches the peer.
    """

    def __init__(self, *args: Any, ssrf_team_id: int | None = None, **kwargs: Any) -> None:
        self._ssrf_team_id = ssrf_team_id
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        super().connect()
        _enforce_peer_ip_safe(self.host, self.sock, self._ssrf_team_id)


class _SSRFGuardedHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _SSRFGuardedHTTPConnection


class _SSRFGuardedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _SSRFGuardedHTTPSConnection


class _SSRFGuardedPoolManager(PoolManager):
    """`PoolManager` whose pools open peer-IP-checking connections.

    `ssrf_team_id` is threaded onto each pool's `conn_kw` in `_new_pool`, not
    passed via `connection_pool_kw` — `PoolManager` hashes that dict into a
    fixed-field `PoolKey` namedtuple that rejects unknown keys.
    """

    def __init__(self, *args: Any, ssrf_team_id: int | None = None, **kwargs: Any) -> None:
        self._ssrf_team_id = ssrf_team_id
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {
            "http": _SSRFGuardedHTTPConnectionPool,
            "https": _SSRFGuardedHTTPSConnectionPool,
        }

    def _new_pool(
        self,
        scheme: str,
        host: str,
        port: int,
        request_context: dict[str, Any] | None = None,
    ) -> HTTPConnectionPool:
        pool = super()._new_pool(scheme, host, port, request_context=request_context)
        # Every connection this pool opens needs the allowlist team to vet the
        # peer it lands on; `conn_kw` is forwarded verbatim to the connection.
        pool.conn_kw["ssrf_team_id"] = self._ssrf_team_id
        return pool


class SSRFGuardedHTTPAdapter(TrackedHTTPAdapter):
    """`TrackedHTTPAdapter` that rejects requests to internal/private hosts.

    Two layers:

    1. A cheap pre-flight check in `send()` rejects request URLs that name a
       literal private IP or `localhost`, and URLs with no hostname at all,
       before a socket is opened. It does no DNS resolution — it only fails
       blatant misconfiguration fast, with a clear error.
    2. A post-connect check in the connection layer validates the IP the
       socket *actually* connected to, via `getpeername()`. This is the
       authoritative layer: it vets the real peer of every connection —
       hostname targets the pre-flight can't resolve, and the runtime
       pagination/redirect targets static config never sees. Inspecting the
       live socket makes it immune to DNS rebinding: a resolver cannot change
       the IP of a socket that is already open, so the request is never sent
       if the peer is internal.

    Both layers consult `_is_host_safe`, which is a no-op outside PostHog
    Cloud, so this adds nothing for self-hosted instances.

    `team_id` selects the team whose internal-host allowlist applies; `None`
    means no team context, so no allowlist exemption is granted and the host
    is checked unconditionally.

    Known limitation: if an HTTP proxy is configured, requests routes through
    a separate proxy pool manager, so only the pre-flight URL check runs —
    the post-connect peer check is bypassed. `make_tracked_session` sets
    `trust_env=False` so HTTP(S)_PROXY env vars can't trigger this silently;
    data-warehouse sources don't configure a proxy in code either, so this
    isn't a gap in practice.
    """

    # Pickling: `_team_id` must round-trip so an unpickled adapter rebuilds
    # its pool manager with the same allowlist team.
    __attrs__ = [*HTTPAdapter.__attrs__, "_team_id"]

    def __init__(self, team_id: int | None = None, **kwargs: Any) -> None:
        # Set before `super().__init__()`: it calls `init_poolmanager()`,
        # which reads `_team_id` to thread it down into the connection pool.
        self._team_id = team_id
        super().__init__(**kwargs)

    def init_poolmanager(
        self,
        connections: int,
        maxsize: int,
        block: bool = DEFAULT_POOLBLOCK,
        **pool_kwargs: Any,
    ) -> None:
        self.poolmanager = _SSRFGuardedPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssrf_team_id=getattr(self, "_team_id", None),
            **pool_kwargs,
        )

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        host = urlparse(request.url or "").hostname
        if not host:
            record_blocked_request(
                host=request.url or "", team_id=self._team_id, reason="request URL has no hostname", layer="preflight"
            )
            raise BlockedHostError(f"Request URL {request.url!r} is missing a hostname")
        # Cheap, no-DNS pre-flight: catches literal private IPs / localhost
        # fast. Hostname targets pass here and are vetted authoritatively by
        # the post-connect peer check (see `SSRFGuardedHTTPAdapter`).
        ok, err = _is_host_safe(host, self._team_id, resolve=False)
        if not ok:
            reason = err or "host is not allowed"
            record_blocked_request(host=host, team_id=self._team_id, reason=reason, layer="preflight")
            raise BlockedHostError(f"Blocked request to host {host!r}: {reason}")
        return super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


def make_tracked_adapter(
    retry: Retry | None = None,
    *,
    team_id: int | None = None,
    allow_internal_ips: bool = False,
    **kwargs: Any,
) -> TrackedHTTPAdapter:
    """Construct a tracked HTTP adapter.

    By default returns an `SSRFGuardedHTTPAdapter` — it rejects requests to
    internal/private hosts, re-validating the peer the socket actually
    connected to so DNS rebinding can't slip an internal IP past it. The
    guard is a no-op outside PostHog Cloud.

    Pass `allow_internal_ips=True` to opt out of the guard entirely and get a
    plain `TrackedHTTPAdapter`. This is a deliberate, secure-by-default escape
    hatch for the rare caller that must reach internal infrastructure — use
    it sparingly and only where the destination is trusted.

    `retry=None` (the default) uses the built-in `DEFAULT_RETRY` policy. To
    truly opt out of retries, pass `retry=Retry(total=0)`. To override with
    different retry settings, pass a custom `Retry` instance. Any extra
    kwargs are forwarded to `HTTPAdapter.__init__`.

    `team_id` is the team whose internal-host allowlist applies. Pass it
    whenever it's known so allowlisted teams keep their exemption; `None`
    just means no team context and no exemption.
    """
    if retry is None:
        retry = DEFAULT_RETRY
    if allow_internal_ips:
        return TrackedHTTPAdapter(max_retries=retry, **kwargs)
    return SSRFGuardedHTTPAdapter(team_id=team_id, max_retries=retry, **kwargs)


def make_tracked_session(
    *,
    retry: Retry | None = None,
    headers: dict[str, str] | None = None,
    team_id: int | None = None,
    allow_internal_ips: bool = False,
) -> requests.Session:
    """Return a fresh `requests.Session` with tracked, SSRF-guarded adapters.

    By default every session this returns rejects requests to internal/
    private hosts — including runtime pagination and redirect targets — and
    re-checks the peer the socket actually connected to. See
    `make_tracked_adapter` for the `retry` parameter semantics — `None` uses
    `DEFAULT_RETRY`; pass `Retry(total=0)` to disable retries.

    Pass `allow_internal_ips=True` to opt out of the SSRF guard — a
    deliberate escape hatch for callers that must reach internal hosts; use
    it sparingly.

    `team_id` is the team whose internal-host allowlist applies. Pass it
    whenever it's known; `None` just means no allowlist exemption.
    """
    session = requests.Session()
    # Don't let HTTP(S)_PROXY env vars route traffic through a proxy: requests
    # proxies via a separate pool manager that bypasses the post-connect peer
    # check. `trust_env=False` makes "no proxy" a guarantee, not an assumption
    # about how workers happen to be configured. It also stops requests from
    # reading a CA bundle from REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE — no
    # data-warehouse worker sets one, and a missing custom CA fails TLS loudly
    # rather than silently, so there's nothing to re-apply.
    session.trust_env = False
    adapter = make_tracked_adapter(retry=retry, team_id=team_id, allow_internal_ips=allow_internal_ips)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if headers:
        session.headers.update(headers)
    return session
