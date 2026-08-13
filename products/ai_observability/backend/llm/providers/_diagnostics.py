import httpx
import posthoganalytics

# Mirrors openai._base_client.DEFAULT_CONNECTION_LIMITS / anthropic._base_client.DEFAULT_CONNECTION_LIMITS.
# Inlined rather than imported because both SDKs expose these via private `_base_client` modules.
# Callers that pass their own `transport` must hand these to the transport instead: httpx applies
# client-level limits only to the transport it builds itself, and silently ignores them otherwise.
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
    transport: httpx.BaseTransport | None = None,
    follow_redirects: bool = True,
) -> httpx.Client:
    return httpx.Client(
        event_hooks={"response": [_tag_response]},
        limits=PROVIDER_DEFAULT_LIMITS,
        follow_redirects=follow_redirects,
        timeout=timeout if timeout is not None else httpx.Timeout(connect=5.0, read=600, write=600, pool=600),
        transport=transport,
    )
