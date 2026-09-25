from typing import Any

import httpx
import posthoganalytics

from posthog.security.pinned_httpx import pinned_client
from posthog.security.url_validation import ResolvedIPs

# Mirrors openai._base_client.DEFAULT_CONNECTION_LIMITS / anthropic._base_client.DEFAULT_CONNECTION_LIMITS.
# Inlined rather than imported because both SDKs expose these via private `_base_client` modules.
PROVIDER_DEFAULT_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=100, keepalive_expiry=5.0)


def _tag_response(response: httpx.Response) -> None:
    try:
        posthoganalytics.tag("provider.last_status", response.status_code)
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("anthropic-request-id")
            or response.headers.get("openai-request-id")
        )
        if request_id:
            posthoganalytics.tag("provider.last_request_id", request_id)
    except Exception:
        pass  # instrumentation must never break the call


def tagged_http_client(
    timeout: float | None = None,
    *,
    pin: tuple[str, ResolvedIPs] | None = None,
    follow_redirects: bool = True,
) -> httpx.Client:
    """An httpx client that tags provider responses.

    ``pin`` is the ``(url, validated addresses)`` pair from ``validate_url_and_pin_ips``. Passing it
    restricts the client to those addresses, so a record that rebinds after validation has nothing
    left to redirect. The two travel together because a pin only means anything for the URL it was
    validated for.
    """
    kwargs: dict[str, Any] = {
        "event_hooks": {"response": [_tag_response]},
        "limits": PROVIDER_DEFAULT_LIMITS,
        "follow_redirects": follow_redirects,
        "timeout": timeout if timeout is not None else httpx.Timeout(connect=5.0, read=600, write=600, pool=600),
    }
    if pin is None:
        return httpx.Client(**kwargs)
    url, pinned_ips = pin
    return pinned_client(url, pinned_ips, **kwargs)
