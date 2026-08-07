"""Server-side analytics for widget submissions that never became a ticket.

`support ticket send blocked` (frontend, supportLogic.ts) covers messages that never left the
browser. This covers the other half: requests that reached us and were refused. They are
complementary rather than redundant — an ad blocker suppresses the client event and neither one
survives a network drop, and only the server knows which field it rejected and why.

This event lands in PostHog's own project (posthoganalytics is keyed to it in posthog/apps.py),
not the customer's. That rules out reserved property names: `$session_id`, `$current_url` and
`distinct_id` describe a session and a person that live in the *customer's* project, so attaching
them here would manufacture phantom sessions and persons in ours, and a `distinct_id` property
would shadow the event's real one. Everything client-supplied is therefore prefixed `client_` or
named plainly.

WidgetMessageView is AllowAny and most of these exits happen before validation, so treat every
value read here as attacker-controlled: type-check it, truncate it, and bound how many entries can
be recorded.
"""

import re
import uuid
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

from rest_framework.request import Request
from rest_framework.serializers import Serializer

from posthog.api.utils import parse_domain
from posthog.event_usage import report_team_action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

SEND_FAILED_EVENT = "support ticket send failed"


class SendFailureReason(StrEnum):
    """One constant per exit from WidgetMessageView.post that returns without a message.

    An enum rather than bare strings so adding an exit without a reason is visibly wrong, and so a
    typo at a call site fails at import rather than silently splitting a series. The values are the
    breakdown key on the event, so renaming one breaks continuity.
    """

    HONEYPOT = "honeypot"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"
    VALIDATION_ERROR = "validation_error"
    IDENTITY_VERIFICATION_FAILED = "identity_verification_failed"
    IDENTITY_NOT_CONFIGURED = "identity_not_configured"
    NO_AUTH_CONTEXT = "no_auth_context"
    INVALID_TICKET_ID = "invalid_ticket_id"
    # Two exits, not one: an identity-mode rejection is a person-merge problem and a session-mode
    # rejection is a localStorage problem. auth_mode can't separate them, because the widget sends
    # both sets of fields once a user is identified.
    TICKET_FORBIDDEN_IDENTITY = "ticket_forbidden_identity"
    TICKET_FORBIDDEN_SESSION = "ticket_forbidden_session"
    TICKET_NOT_FOUND = "ticket_not_found"
    RATE_LIMITED = "rate_limited"


# Caps on what reaches the event, not on what the request may contain. The body is already bounded
# by DATA_UPLOAD_MAX_MEMORY_SIZE; these bound the *analytics* payload so a stuffed request can't
# inflate it.
_MAX_ID_LENGTH = 400  # matches WidgetMessageSerializer.distinct_id, so a valid id is never cut
_MAX_SESSION_ID_LENGTH = 64  # matches WidgetMessageSerializer.session_id
_MAX_URL_LENGTH = 500
_MAX_HOST_LENGTH = 100
_MAX_KEY_LENGTH = 50
_MAX_PAYLOAD_KEYS = 25
_MAX_ERROR_FIELDS = 25
_MAX_ERROR_DEPTH = 3

# One rate_limited event per team per window. DRF's SimpleRateThrottle.throttle_failure records
# nothing, so the throttle bounds *allowed* requests, not denied ones — without this, a client stuck
# in a retry loop emits an event per rejected request rather than one per problem.
_RATE_LIMITED_REPORT_TTL_SECONDS = 60

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def _bounded_str(value: Any, max_length: int) -> str | None:
    """Genuine non-empty strings only, stripped of control characters and truncated.

    Deliberately does not coerce: a client sending `{"session_id": {...}}` is a bug worth seeing as
    a missing value, not worth serialising an arbitrary object into an event property. Control
    characters are dropped for the same reason sanitize_header_value drops them — these land in a
    console-and-browser UI that staff read.
    """
    if not isinstance(value, str) or not value:
        return None
    return _CONTROL_CHARACTERS.sub("", value)[:max_length] or None


def _host(url: Any) -> str | None:
    """Hostname only. urlparse raises ValueError on a malformed IPv6 authority."""
    if not isinstance(url, str):
        return None
    try:
        hostname = parse_domain(url)
    except ValueError:
        return None
    return hostname[:_MAX_HOST_LENGTH].lower() if hostname else None


def _url_path(url: Any) -> str | None:
    """The path, without host, query or fragment.

    Recorded instead of the full URL. `current_url` is client-supplied on an unauthenticated
    endpoint and PropertiesTable renders any URL-shaped property value as a clickable link, so
    storing a whole URL would reopen the hole _trusted_replay_url exists to close. Dropping the
    query string also keeps reset tokens, emails and record ids — routinely in a customer's URLs —
    out of PostHog's own project. Host is reported separately, so "which page" survives intact.
    """
    if not isinstance(url, str):
        return None
    try:
        return _bounded_str(urlparse(url).path, _MAX_URL_LENGTH)
    except ValueError:
        return None


def _trusted_replay_url(value: Any) -> str | None:
    """A replay link is recorded only when it points at PostHog.

    The URL is client-supplied on an unauthenticated endpoint, and the event it lands in is read by
    PostHog staff in our own project, where the UI renders URL properties as clickable links.
    Without this check anyone holding a public widget token could plant an arbitrary link in front
    of an engineer. It costs nothing: a real replay URL is always on a PostHog host.
    """
    url = _bounded_str(value, _MAX_URL_LENGTH)
    if url is None:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname == "posthog.com" or hostname.endswith(".posthog.com") or hostname == _host(settings.SITE_URL):
        return url
    return None


def _ticket_uuid(value: Any) -> str | None:
    """Only a parseable UUID.

    An unparseable ticket_id is attacker-controlled free text, so recording it verbatim would be
    unbounded cardinality — and `reason=invalid_ticket_id` already says it was garbage.
    """
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _first_code(detail: Any, depth: int = 0) -> str | None:
    """First DRF error `code` inside a possibly-nested error detail.

    `serializer.errors` is field -> list[ErrorDetail], and ErrorDetail is a str subclass carrying
    `.code`. Two shapes deviate: non-field errors land under "non_field_errors" with the same list
    shape, and a nested DictField or child serializer yields field -> {inner_key: [ErrorDetail]}.
    The nested shape doesn't happen for WidgetMessageSerializer today — its DictFields use the
    default unvalidated child, which cannot fail — but it will the day someone adds `child=`, and
    this must not start dropping codes or raising then.

    Depth-bounded, because this runs on an error path where a second failure would mask the first.
    """
    if depth > _MAX_ERROR_DEPTH:
        return None
    if isinstance(detail, list | tuple):
        for item in detail:
            code = _first_code(item, depth + 1)
            if code:
                return code
        return None
    if isinstance(detail, dict):
        for item in detail.values():
            code = _first_code(item, depth + 1)
            if code:
                return code
        return None
    code = getattr(detail, "code", None)
    if isinstance(code, str):
        return code[:_MAX_KEY_LENGTH]
    # A plain str can appear if a validator was handed one directly. "unknown" beats a missing key:
    # a breakdown showing "unknown" is a bug report, a missing key is invisible.
    return "unknown" if isinstance(detail, str) else None


def _error_codes(errors: Any) -> dict[str, str]:
    """field -> the code that rejected it, e.g. {"message": "max_length"}.

    Codes rather than messages: DRF's codes are a small closed vocabulary ("required", "blank",
    "max_length", "invalid", "null", "not_a_dict"), so they break down cleanly, while messages are
    prose that gets reworded and would put a sentence into a property value.

    One code per field, because a field almost always fails one check first and a flat string map
    stays readable in HogQL without unnesting.
    """
    codes: dict[str, str] = {}
    if not isinstance(errors, dict):
        return codes
    for field, detail in list(errors.items())[:_MAX_ERROR_FIELDS]:
        if not isinstance(field, str):
            continue
        code = _first_code(detail)
        if code:
            codes[field[:_MAX_KEY_LENGTH]] = code
    return codes


def _bounded_keys(source: Any, limit: int) -> list[str]:
    """Sorted, truncated, deduplicated string keys — a bound on cardinality, not a faithful copy.

    Sorts and dedupes before slicing, so the result depends on the key set rather than on the order
    the JSON parser happened to see it in. Slicing first would make the same logical payload
    produce different values across requests, and would leave duplicates behind when two long keys
    truncate to the same prefix.
    """
    if not isinstance(source, dict):
        return []
    return sorted({key[:_MAX_KEY_LENGTH] for key in source if isinstance(key, str)})[:limit]


def _auth_mode(data: dict) -> str:
    """Which access-control path the client attempted. Four values, so it breaks down."""
    has_identity = bool(data.get("identity_distinct_id")) and bool(data.get("identity_hash"))
    has_session = bool(data.get("widget_session_id"))
    if has_identity and has_session:
        return "both"
    if has_identity:
        return "identity"
    if has_session:
        return "widget_session"
    return "none"


def report_widget_send_failed(
    team: Team,
    request: Request,
    reason: SendFailureReason,
    *,
    serializer: Serializer | None = None,
) -> None:
    """Record a widget message that was rejected, with enough context to act on it.

    Never raises. Every call site is already returning an error to the customer; losing the
    analytics must not turn a 400 into a 500.

    `serializer` is optional because the earliest exits happen before or during validation. When it
    is passed and validated cleanly, its `validated_data` is preferred over the raw body: the
    serializer has already type-checked and truncated those fields, so the recorded values match
    what a successful request would have stored. When it failed, only the raw body is available and
    every read is defended. Callers must have called `is_valid()` first — `.errors` and
    `.validated_data` assert on that.
    """
    try:
        # request.data is a list or a str for a non-object JSON body, where `.get` would raise.
        raw = request.data if isinstance(request.data, dict) else {}
        errors = serializer.errors if serializer is not None else {}
        validated = serializer.validated_data if serializer is not None and not errors else {}
        source = validated or raw

        session_context = source.get("session_context")
        if not isinstance(session_context, dict):
            session_context = {}
        current_url = session_context.get("current_url")

        raw_ticket_id = raw.get("ticket_id")
        message = source.get("message")

        report_team_action(
            team,
            SEND_FAILED_EVENT,
            {
                "channel_source": "widget",
                "reason": str(reason),
                "error_fields": _bounded_keys(errors, _MAX_ERROR_FIELDS),
                "error_codes": _error_codes(errors),
                # Length, never content — but "was there a draft at all" separates a customer who
                # lost words from a bot probing the endpoint.
                "had_message": bool(_bounded_str(message, 1)),
                "message_length": len(message) if isinstance(message, str) else 0,
                "auth_mode": _auth_mode(source),
                "is_new_ticket": not raw_ticket_id,
                "ticket_id": _ticket_uuid(raw_ticket_id),
                "client_session_id": _bounded_str(source.get("session_id"), _MAX_SESSION_ID_LENGTH),
                "client_distinct_id": _bounded_str(
                    source.get("distinct_id") or source.get("identity_distinct_id"), _MAX_ID_LENGTH
                ),
                "session_replay_url": _trusted_replay_url(session_context.get("session_replay_url")),
                # Split rather than stored whole — see _url_path.
                "current_url_host": _host(current_url),
                "current_url_path": _url_path(current_url),
                # Presence only. Trait values are the customer's own name and email.
                "has_traits": bool(source.get("traits")),
                # Browser-attested, so this is the domain a team actually has to allowlist. Falls
                # back per-header rather than on the raw string: a sandboxed iframe sends the
                # literal "Origin: null", which is truthy but has no host.
                "origin_host": _host(request.headers.get("Origin")) or _host(request.headers.get("Referer")),
                "payload_shape": type(request.data).__name__[:_MAX_KEY_LENGTH],
                "payload_keys": _bounded_keys(raw, _MAX_PAYLOAD_KEYS),
            },
        )
    except Exception as e:
        capture_exception(e)


def report_widget_rate_limited(team: Team, request: Request) -> None:
    """Record a throttled send, at most once per team per window.

    Needs its own entry point because the throttle offers no backpressure here: DRF's
    SimpleRateThrottle only writes to the cache on success, so once a caller is over the limit
    every further request is a fresh denial. Reporting each one would let anyone holding a public
    widget token drive unbounded event volume into PostHog's own project. One event per window says
    the same thing — this team is hitting the limit — at a bounded cost.

    cache.add is the dedupe: it sets the key only when absent, so the first caller in the window
    reports and the rest are no-ops.
    """
    try:
        if not cache.add(
            f"conversations/send-failed-rate-limited/{team.id}", True, timeout=_RATE_LIMITED_REPORT_TTL_SECONDS
        ):
            return
    except Exception as e:
        # A cache outage must not silently turn the dedupe off, so fail closed and report nothing.
        capture_exception(e)
        return
    report_widget_send_failed(team, request, SendFailureReason.RATE_LIMITED)
