"""What every HTTP transport sends the same way: the JSON post, the credential digest, timestamps.

Each transport's credential, a webhook URL or a PagerDuty routing key, never reaches an error
message, a log line or a metric label, so the errors here name a status or an exception class only.
"""

import json
import time
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

import requests

from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

from products.alerts_platform.backend.delivery.transport import DeliveryError, DestinationRefused

# Request Timeout and Too Many Requests: the destination accepts this request at another time.
_RETRYABLE_CLIENT_ERRORS: Final = frozenset({408, 429})

# Enough for a provider's error JSON, and small enough that no answer can fill the worker's memory.
_MAX_REFUSAL_BODY_BYTES: Final = 4096
# The whole refusal body read finishes within this time, so a destination that sends it slowly
# cannot hold the send past the deliver activity's 10-second start_to_close.
_REFUSAL_BODY_TIMEOUT_SECONDS: Final = 1.0

# Both fit inside the deliver activity's 10-second start_to_close, so a stalled destination fails
# this attempt instead of outliving it. A send still in flight when Temporal starts the next
# attempt posts a second copy, because no webhook provider takes an idempotency key.
CONNECT_TIMEOUT_SECONDS: Final = 3.0
READ_TIMEOUT_SECONDS: Final = 5.0


def credential_digest(credential: str) -> str:
    """What the thread store keys a destination on, because the row would otherwise store the credential."""
    return hashlib.sha256(credential.encode()).hexdigest()


def rfc3339(moment: datetime) -> str:
    # The ClickHouse HTTP client returns naive datetimes. The history columns hold UTC, and
    # receivers reject a timestamp with no offset.
    aware = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return aware.isoformat()


def post_json(
    url: str,
    body: dict[str, Any],
    *,
    display_name: str,
    headers: dict[str, str] | None = None,
    owner_refusals: Mapping[int, bytes | None] | None = None,
) -> None:
    """Posts `body` as JSON, raising `DestinationRefused` for a 4xx the destination's owner can fix.

    `owner_refusals` maps each such 4xx to None, or to the lowercase text that only the owner's
    mistake carries when the provider answers PostHog's mistakes with the same status. None means
    every 4xx except 408 and 429.
    """
    try:
        # `pinned_session` validates the URL and connects to the IPs it validated, which
        # closes the window where DNS changes between the check and the connection.
        with pinned_session(url) as session:
            request = session.prepare_request(
                requests.Request(
                    "POST",
                    url,
                    # UTF-8 rather than `json=`, which escapes every non-ASCII character to six
                    # bytes or more. A provider limits the bytes it receives, so a body sized by
                    # its UTF-8 length must be sent as UTF-8.
                    data=json.dumps(body, ensure_ascii=False).encode(),
                    headers={"Content-Type": "application/json", **(headers or {})},
                )
            )
            settings = session.merge_environment_settings(request.url, {}, True, None, None)
            # The adapter rather than `session.send`, and `stream=True` with no read. Even with
            # redirects off, the session reads a redirect's whole body to work out where it
            # points, so a destination answering 3xx with an unbounded body would fill the
            # worker's memory. The adapter returns the response unread and follows nothing.
            response = session.get_adapter(request.url or url).send(
                request,
                stream=True,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                # Typed as optional, but it falls back to the session's own setting, which is True.
                verify=True if settings["verify"] is None else settings["verify"],
                cert=settings["cert"],
                proxies=settings["proxies"],
            )
            status = response.status_code
            refused = _is_owner_refusal(status, response, owner_refusals)
            response.close()
    except SSRFBlockedError:
        raise DeliveryError(
            f"The {display_name} destination URL points to an address PostHog does not send to."
        ) from None
    except requests.RequestException as error:
        # Only the class name, and `from None` to keep the original out of the failure chain:
        # the text of a `requests` error carries the whole URL.
        raise DeliveryError(f"The {display_name} destination could not be reached: {type(error).__name__}") from None
    if not 200 <= status < 300:
        refusal = f"The {display_name} destination refused the message with status {status}."
        if refused:
            raise DestinationRefused(refusal)
        raise DeliveryError(refusal)


def _is_owner_refusal(
    status: int, response: requests.Response, owner_refusals: Mapping[int, bytes | None] | None
) -> bool:
    if not 400 <= status < 500 or status in _RETRYABLE_CLIENT_ERRORS:
        return False
    if owner_refusals is None:
        return True
    if status not in owner_refusals:
        return False
    marker = owner_refusals[status]
    if marker is None:
        return True
    # A compressed body would decode past the cap, so only a plain one is read.
    if response.headers.get("Content-Encoding", "identity") != "identity":
        return False
    try:
        return _body_carries(response.raw, marker)
    except Exception:
        # urllib3 raises its own errors here, which `requests` does not wrap. A body that cannot
        # be read leaves whose fix it is unknown, and an unknown refusal is not the owner's.
        return False


def _body_carries(raw: Any, marker: bytes) -> bool:
    """Reads fragments until the marker shows, the body ends, the cap fills or the deadline passes.

    Each receive waits only for what is left of the deadline. `read(n)` would instead keep
    receiving until it had n bytes, however slowly they arrived.
    """
    sock = getattr(getattr(raw, "connection", None), "sock", None)
    # urllib3 1.26 has no `read1`, so the call goes to the `http.client` response it wraps, which
    # returns the raw bytes, still undecoded.
    reader = getattr(raw, "_fp", raw)
    deadline = time.monotonic() + _REFUSAL_BODY_TIMEOUT_SECONDS
    head = b""
    while marker not in head.lower() and len(head) < _MAX_REFUSAL_BODY_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if sock is not None:
            sock.settimeout(remaining)
        fragment = reader.read1(_MAX_REFUSAL_BODY_BYTES - len(head))
        if not fragment:
            break
        head += fragment
    return marker in head.lower()
