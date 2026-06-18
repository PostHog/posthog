"""Send push notifications to mobile devices via the Expo push service.

The Expo push API accepts up to 100 messages per HTTP call and returns one
ticket per message. Tickets carry transient errors (delivery failed, push token
invalid) but final delivery success is only confirmed by polling receipts.

For the PostHog Code mobile app the only thing we care about is best-effort
fan-out plus pruning tokens the device push service has rejected as
permanently invalid (`DeviceNotRegistered`). Receipt polling is deferred until
we have a real reason to surface delivery status.

Reference: https://docs.expo.dev/push-notifications/sending-notifications/
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any, cast

import requests
import structlog

from posthog.models.user import User
from posthog.models.user_push_token import UserPushToken

logger = structlog.get_logger(__name__)

EXPO_PUSH_API_URL = "https://exp.host/--/api/v2/push/send"
EXPO_PUSH_API_TIMEOUT_SECONDS = 10
EXPO_PUSH_BATCH_SIZE = 100


def send_push_to_user(
    user: User,
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    suppressed_push_token_ids: Iterable[uuid.UUID | str] | None = None,
) -> int:
    """Send a push notification to every device registered for ``user``.

    ``suppressed_push_token_ids`` lets the caller (typically a feature-specific
    dispatcher) drop devices that have proven they're already watching the
    relevant context — e.g. presence beacons on a PostHog Code task. Tokens
    whose ``UserPushToken.id`` is in the set are skipped before fanout, even
    if that leaves the user with zero recipients. The contract is "if any
    device is provably watching, suppress the others", so an empty post-filter
    list intentionally results in no push being sent.

    Returns the number of messages the Expo service accepted (i.e. for which
    a non-error ticket was returned). Tokens flagged by Expo as
    ``DeviceNotRegistered`` are deleted for this user so we stop trying to
    deliver to dead devices.
    """
    qs = UserPushToken.objects.filter(user=user)
    if suppressed_push_token_ids:
        qs = qs.exclude(id__in=list(suppressed_push_token_ids))
    tokens = list(qs.values_list("token", flat=True))
    if not tokens:
        return 0

    accepted = 0
    for batch in _chunk(tokens, EXPO_PUSH_BATCH_SIZE):
        accepted += _send_batch(user, batch, title=title, body=body, data=data)
    return accepted


def _send_batch(
    user: User,
    tokens: list[str],
    *,
    title: str,
    body: str,
    data: dict[str, Any] | None,
) -> int:
    payload = [
        {
            "to": token,
            "title": title,
            "body": body,
            "sound": "default",
            "data": data or {},
        }
        for token in tokens
    ]

    try:
        response = requests.post(
            EXPO_PUSH_API_URL,
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=EXPO_PUSH_API_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("expo_push.request_failed", error=str(exc), token_count=len(tokens))
        return 0

    if response.status_code >= 500:
        logger.warning(
            "expo_push.server_error",
            status_code=response.status_code,
            token_count=len(tokens),
        )
        return 0
    if response.status_code >= 400:
        logger.warning(
            "expo_push.client_error",
            status_code=response.status_code,
            token_count=len(tokens),
            body=response.text[:500],
        )
        return 0

    try:
        body_json = response.json()
    except ValueError:
        logger.warning("expo_push.invalid_response", body=response.text[:500])
        return 0

    tickets = body_json.get("data", []) if isinstance(body_json, dict) else []
    if not isinstance(tickets, list):
        return 0

    # Expo's contract is one ticket per message in order. If we ever get a
    # mismatch, `zip` silently truncates and the tail tokens fall into a hole
    # — never counted as accepted, never pruned. Log so a contract regression
    # shows up in monitoring instead of looking like quiet success.
    if len(tickets) != len(tokens):
        logger.warning(
            "expo_push.ticket_count_mismatch",
            expected=len(tokens),
            received=len(tickets),
        )

    accepted = 0
    invalid_tokens: list[str] = []
    for token, ticket in zip(tokens, tickets):
        if not isinstance(ticket, dict):
            continue
        if ticket.get("status") == "ok":
            accepted += 1
            continue
        details = ticket.get("details") if isinstance(ticket.get("details"), dict) else {}
        error_code = cast(dict, details).get("error")
        if error_code == "DeviceNotRegistered":
            invalid_tokens.append(token)
        else:
            logger.warning(
                "expo_push.ticket_error",
                error=error_code,
                message=ticket.get("message"),
            )

    if invalid_tokens:
        # Scope pruning to this user — the same opaque token string could
        # theoretically belong to another user (e.g. shared test device), and
        # we should never delete a row we don't own the dispatch context for.
        UserPushToken.objects.filter(user=user, token__in=invalid_tokens).delete()
        logger.info("expo_push.pruned_invalid_tokens", count=len(invalid_tokens), user_id=user.id)

    return accepted


def _chunk(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
