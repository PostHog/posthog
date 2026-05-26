"""Tracked `requests.Session` factory.

`make_tracked_session(...)` returns a `requests.Session` whose adapters
intercept every dispatched request to feed the observer. Vendor SDKs that
accept a `requests.Session` (Stripe via `stripe.RequestsClient`, gspread,
hubspot-api-client, etc.) can be handed the result of this factory.

The intercept point is the adapter's `send()` rather than a `Session`
subclass, because some SDKs construct their own `Session` and we still
want the metering — they only need to mount the tracked adapter:

    session.mount("https://", make_tracked_adapter(...))
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import requests
from requests import PreparedRequest, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from posthog.temporal.data_imports.sources.common.http.observer import record_request

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


def make_tracked_adapter(retry: Retry | None = None, **kwargs: Any) -> TrackedHTTPAdapter:
    """Construct a `TrackedHTTPAdapter`.

    `retry=None` (the default) uses the built-in `DEFAULT_RETRY` policy. To
    truly opt out of retries, pass `retry=Retry(total=0)`. To override with
    different retry settings, pass a custom `Retry` instance. Any extra
    kwargs are forwarded to `HTTPAdapter.__init__`.
    """
    if retry is None:
        retry = DEFAULT_RETRY
    return TrackedHTTPAdapter(max_retries=retry, **kwargs)


def make_tracked_session(
    *,
    retry: Retry | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Session:
    """Return a fresh `requests.Session` with tracked HTTP/HTTPS adapters.

    See `make_tracked_adapter` for the `retry` parameter semantics — `None`
    uses `DEFAULT_RETRY`; pass `Retry(total=0)` to disable retries.
    """
    session = requests.Session()
    adapter = make_tracked_adapter(retry=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if headers:
        session.headers.update(headers)
    return session
