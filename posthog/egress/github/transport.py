"""GitHub incarnation of the egress transport.

``github_request`` is the one way to call GitHub from anywhere in the codebase: it gates on the shared
per-installation budget and records telemetry by construction, so a caller physically can't forget
either. It is *token-agnostic* — pass whatever ``Authorization`` header the caller holds (installation
token, user token, PAT, or PostHog's shared token) and the ``installation_id`` as ``scope`` when known.

This module lives in ``egress`` (not the model layer) and imports nothing from ``posthog.models`` — the
model-coupled ``GitHubIntegrationBase`` is a *consumer* of this, not the other way round. ``GITHUB_API_VERSION``
is defined here for the same reason: the transport needs it, and it can't reach back into ``integration.py``.
"""

import time
import hashlib
from typing import Any

from django.conf import settings

import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers

from posthog.dataclasses import frozen
from posthog.egress.github.limiter import classify_github_resource, consume_github_installation_sync
from posthog.egress.github.observability import (
    record_github_api_exception,
    record_github_api_response,
    record_github_conditional_cache,
)
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient
from posthog.utils import get_safe_cache, safe_cache_set

# The GitHub REST API version we pin every request to. Lives here (not integration.py) so the egress
# layer stays free of any posthog.models import; integration.py imports it back from here.
GITHUB_API_VERSION = "2022-11-28"

_CONDITIONAL_CACHE_PREFIX = "github_egress:conditional:v1"

# Replayed from the stored entry, because a 304 need not repeat them and a caller that reads .text or
# branches on the media type would otherwise sniff a body we already know the type of.
_STORED_HEADERS = frozenset({"content-type", "content-language", "content-disposition", "link", "last-modified"})

# Taken from the live 304 instead, because they describe this exchange rather than the stored body.
_LIVE_HEADERS = frozenset({"etag", "date", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"})

# A request the caller already made conditional is theirs to interpret; we stand down entirely.
_CALLER_CONDITIONAL_HEADERS = frozenset(
    {"if-none-match", "if-modified-since", "if-match", "if-unmodified-since", "if-range"}
)

# Vary dimensions the key already accounts for: `accept` is in it, `authorization` is subsumed by the
# caller-declared identity, and requests decodes `accept-encoding` before we store. Anything else (or
# `*`) means GitHub varies on something we do not key on, so we decline to store.
_VARY_ACCOUNTED_FOR = frozenset({"accept", "authorization", "accept-encoding"})


@frozen
class _CachedResponse:
    etag: str
    body: bytes
    headers: dict[str, str]


def _conditional_cache_key(identity: str, accept: str, method: str, url: str, params: object) -> str:
    prepared = requests.Request(method=method, url=url, params=params).prepare().url or url
    digest = hashlib.sha256(f"{accept}\n{prepared}".encode()).hexdigest()
    return f"{_CONDITIONAL_CACHE_PREFIX}:{identity}:{digest}"


def _storable(response: requests.Response) -> bool:
    if response.status_code != 200 or not response.headers.get("etag"):
        return False
    vary = {token.strip().lower() for token in response.headers.get("vary", "").split(",") if token.strip()}
    if not vary <= _VARY_ACCOUNTED_FOR:
        return False
    if "no-store" in response.headers.get("cache-control", "").lower():
        return False
    return len(response.content) <= settings.GITHUB_EGRESS_CONDITIONAL_CACHE_MAX_BODY_BYTES


def _replayed(response: requests.Response, cached: _CachedResponse) -> requests.Response:
    """A 200 carrying the cached body, so callers never have to know the request was conditional.

    The stored headers describe the body; the live ones describe this exchange. A 304 need not repeat
    Content-Type, and a caller that reads ``.text`` would otherwise sniff a charset we already know.
    """
    replay = requests.models.Response()
    replay.status_code = 200
    replay.reason = "OK"
    replay.headers = CaseInsensitiveDict(cached.headers)
    replay.headers.update({name: value for name, value in response.headers.items() if name.lower() in _LIVE_HEADERS})
    replay.encoding = get_encoding_from_headers(replay.headers)
    replay.url = response.url
    replay.request = response.request
    replay.elapsed = response.elapsed
    replay._content = cached.body
    # Same two attributes requests settles in Response.__setstate__ when it restores a deserialized
    # response. Without the flag, iter_content takes the streaming branch and reads the None raw.
    replay._content_consumed = True  # type: ignore[attr-defined]
    replay.raw = None
    return replay


class GitHubEgressBudgetExhausted(EgressBudgetExhausted):
    """A deferrable (BATCH/NORMAL) GitHub call was shed by our egress limiter before it was sent —
    the proactive, our-side twin of :class:`GitHubRateLimitError`. This is our own budget, so a caller
    that can defer (e.g. the warehouse sync) catches it and backs off."""


class GitHubRateLimitError(Exception):
    """GitHub itself rate-limited an outbound call (a 429, or a 403 with a rate-limit body) — the
    reactive, GitHub-side twin of :class:`GitHubEgressBudgetExhausted`. A GitHub egress condition, so it
    lives here (not the model layer); it deliberately does not subclass ``GitHubIntegrationError`` — a
    transient rate limit isn't a fatal integration failure. ``retry_after`` (seconds) is the backoff
    hint; :func:`raise_if_github_rate_limited` always sets it, hand-built instances may not."""

    def __init__(self, message: str, reset_at: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.reset_at = reset_at
        self.retry_after = retry_after


def raise_if_github_rate_limited(response: requests.Response) -> None:
    """Raise :class:`GitHubRateLimitError` when the response signals a GitHub rate limit. Safe to call
    unconditionally after any GitHub API response. Covers every documented signal: secondary 429,
    primary 403 with an exhausted window (``X-RateLimit-Remaining: 0``) or a ``Retry-After`` hint,
    and 403s that only mark the limit in the body (rate limit / abuse detection)."""
    if response.status_code == 429:
        is_rate_limited = True
    elif response.status_code == 403:
        if response.headers.get("retry-after") or response.headers.get("x-ratelimit-remaining") == "0":
            is_rate_limited = True
        else:
            try:
                body = response.text
            except Exception:
                body = ""
            body = body.lower()
            is_rate_limited = "rate limit" in body or "abuse detection" in body
    else:
        return

    if not is_rate_limited:
        return

    def _int_header(name: str) -> int | None:
        val = response.headers.get(name)
        if not val:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    reset_at = _int_header("x-ratelimit-reset")
    retry_after = _int_header("retry-after")
    if retry_after is None and reset_at is not None:
        retry_after = max(1, reset_at - int(time.time()))
    if retry_after is None:
        # No timing headers at all (body-only signal) — GitHub's documented guidance is to wait ≥1 minute.
        retry_after = 60

    raise GitHubRateLimitError(
        f"GitHub API rate limit exceeded (resets at {reset_at})",
        reset_at=reset_at,
        retry_after=retry_after,
    )


class GitHubClient(EgressClient):
    """The GitHub incarnation of :class:`EgressClient`. Stateless and token-agnostic, so one shared
    instance serves every caller; wire it through :func:`github_request`."""

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}

    def conditional_request(
        self,
        method: str,
        url: str,
        *,
        cache_identity: str,
        source: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """``request`` with GitHub's conditional-request support: an unchanged resource comes back as a
        304, which GitHub does not charge against the installation's primary rate limit, and the caller
        gets the stored body as a 200 either way.

        ``cache_identity`` names whose view of the resource this is. It is the caller's to declare
        because the credential decides what the response contains, and installation tokens rotate too
        often to key on directly — see ``GitHubIntegrationBase._installation_cache_scope``.
        """
        merged = {**self._standard_headers(), **(headers or {})}
        declined = (
            method.upper() != "GET"
            or kwargs.get("stream")
            or not settings.GITHUB_EGRESS_CONDITIONAL_CACHE_TTL_SECONDS
            or any(name.lower() in _CALLER_CONDITIONAL_HEADERS for name in merged)
        )
        if declined:
            record_github_conditional_cache("skip", source=source)
            return self.request(method, url, source=source, headers=headers, **kwargs)

        key = _conditional_cache_key(cache_identity, merged["Accept"], method, url, kwargs.get("params"))
        cached = get_safe_cache(key)
        if isinstance(cached, _CachedResponse):
            headers = {**(headers or {}), "If-None-Match": cached.etag}

        response = self.request(method, url, source=source, headers=headers, **kwargs)

        if response.status_code == 304 and isinstance(cached, _CachedResponse):
            record_github_conditional_cache("hit", source=source)
            return _replayed(response, cached)
        record_github_conditional_cache("miss" if cached is not None else "cold", source=source)
        if _storable(response):
            record_github_conditional_cache("store", source=source)
            safe_cache_set(
                key,
                _CachedResponse(
                    etag=response.headers["etag"],
                    body=response.content,
                    headers={
                        name: value for name, value in response.headers.items() if name.lower() in _STORED_HEADERS
                    },
                ),
                settings.GITHUB_EGRESS_CONDITIONAL_CACHE_TTL_SECONDS,
            )
        return response

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_github_installation_sync(
            scope, resource=classify_github_resource(url), priority=priority, source=source
        )

    def _record_response(
        self, response: requests.Response, *, source: str, scope: str | None, method: str, endpoint: str | None
    ) -> None:
        record_github_api_response(response, source=source, installation_id=scope, method=method, endpoint=endpoint)

    def _record_exception(self, *, source: str, scope: str | None, method: str, url: str, endpoint: str | None) -> None:
        record_github_api_exception(source=source, installation_id=scope, method=method, url=url, endpoint=endpoint)

    def _budget_exhausted_error(self, scope: str) -> GitHubEgressBudgetExhausted:
        return GitHubEgressBudgetExhausted(f"GitHub egress budget exhausted for installation {scope}; deferring")


# Stateless — one shared instance for the whole process.
_github_client = GitHubClient()


def github_request(
    method: str,
    url: str,
    *,
    source: str,
    headers: dict[str, str] | None = None,
    installation_id: str | None = None,
    cache_identity: str | None = None,
    priority: Priority = Priority.CRITICAL,
    endpoint: str | None = None,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Make a gated, recorded GitHub API request. ``installation_id`` is the shared budget owner — pass
    it when known so the call is gated (at ``priority``) and the rate-limit gauges are set; leave it
    ``None`` for identity-blind callers (raw PATs, PostHog's public token), which record volume only.
    ``source`` attributes the call to a subsystem. ``headers`` must carry the caller's ``Authorization``.

    ``cache_identity`` opts a GET into conditional requests, naming whose view of the resource this is;
    without it every call goes to GitHub in full. Pass it only when the response depends on nothing
    beyond that identity and the URL — a token narrower than the identity would read another's entry."""
    common: dict[str, Any] = dict(
        scope=installation_id,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
    if cache_identity:
        return _github_client.conditional_request(
            method, url, cache_identity=cache_identity, source=source, headers=headers, **common
        )
    return _github_client.request(method, url, source=source, headers=headers, **common)
