"""SSRF-hardened HTTP requests with DNS pinning.

``validate_url_and_pin_ips`` alone leaves a TOCTOU window: the hostname is
resolved once for validation and again when ``requests`` opens the connection,
so a rebinding DNS record can pass validation and still connect internally.
``PinnedIPAdapter`` closes that window by connecting to the exact IPs that were
validated, and ``pinned_request`` packages the validate → pin → send sequence
for callers that make one-shot requests to externally controlled URLs.

Redirects are never followed automatically — a redirect target has not been
validated. Callers that need to follow one must re-enter ``pinned_request``
with the new URL so every hop is validated and pinned.
"""

import ipaddress
import urllib.parse as urlparse

import requests
from requests.adapters import HTTPAdapter

from posthog.security.url_validation import validate_url_and_pin_ips


class SSRFBlockedError(Exception):
    """URL failed SSRF validation. The message is the block reason."""


class PinnedIPAdapter(HTTPAdapter):
    """
    Requests adapter that rewrites URLs to connect to pre-validated IPs,
    preventing DNS rebinding between validation and connection.

    For HTTPS, sets ``assert_hostname`` and ``server_hostname`` on the
    connection pool so TLS SNI and certificate verification use the
    original hostname (not the IP).

    NOT thread-safe — mount on a single-use ``requests.Session``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pin_map: dict[str, str] = {}
        self._current_original_host: str | None = None

    def pin(self, hostname: str, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        self._pin_map[hostname.lower()] = str(ip)

    def send(  # type: ignore[override]
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: None | float | tuple[float, float] = None,
        verify: bool | str = True,
        cert: None | str | tuple[str, str] = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Response:
        parsed = urlparse.urlparse(request.url or "")
        host = (parsed.hostname or "").lower()
        ip_str = self._pin_map.get(host)

        if ip_str is not None:
            self._current_original_host = host

            ip_netloc = f"[{ip_str}]" if ":" in ip_str else ip_str
            if parsed.port:
                ip_netloc = f"{ip_netloc}:{parsed.port}"

            request.url = urlparse.urlunparse((parsed.scheme, ip_netloc, parsed.path, parsed.params, parsed.query, ""))

            original_netloc = host
            if parsed.port:
                original_netloc = f"{host}:{parsed.port}"
            if request.headers is not None:
                request.headers["Host"] = original_netloc
        else:
            self._current_original_host = None

        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)

    def cert_verify(self, conn: object, url: str, verify: bool | str, cert: None | str | tuple[str, str]) -> None:
        super().cert_verify(conn, url, verify, cert)
        original = getattr(self, "_current_original_host", None)
        if original:
            # We mutate urllib3 pool internals intentionally — these attributes
            # exist at runtime (verified against urllib3 2.6.3) but aren't
            # visible to static type checkers.
            if hasattr(conn, "assert_hostname"):
                conn.assert_hostname = original  # ty: ignore[invalid-assignment]
            # Inject server_hostname into conn_kw so newly created connections
            # use the original hostname for TLS SNI (not the rewritten IP).
            # urllib3 passes **conn_kw to ConnectionCls.__init__, and
            # HTTPSConnection.connect() reads self.server_hostname for SNI.
            if hasattr(conn, "conn_kw") and isinstance(getattr(conn, "conn_kw", None), dict):
                conn.conn_kw["server_hostname"] = original  # ty: ignore[invalid-assignment]


def pinned_request(
    method: str,
    url: str,
    *,
    timeout: float | tuple[float, float],
    headers: dict[str, str] | None = None,
    json: object | None = None,
) -> requests.Response:
    """Send one SSRF-validated HTTP request over a connection pinned to the validated IPs.

    Never follows redirects. Raises ``SSRFBlockedError`` when the URL fails
    validation and lets ``requests.RequestException`` propagate on transport
    failures.
    """
    allowed, reason, pinned_ips = validate_url_and_pin_ips(url)
    if not allowed:
        raise SSRFBlockedError(reason or "URL blocked by SSRF protection")

    adapter = PinnedIPAdapter()
    hostname = (urlparse.urlparse(url).hostname or "").lower()
    if pinned_ips:
        adapter.pin(hostname, next(iter(pinned_ips)))

    session = requests.Session()
    session.mount("http://", adapter)  # nosemgrep: request-session-with-http
    session.mount("https://", adapter)
    try:
        return session.request(method, url, headers=headers, json=json, timeout=timeout, allow_redirects=False)
    finally:
        session.close()
