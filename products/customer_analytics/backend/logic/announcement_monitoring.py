"""Best-effort telemetry for Slack announcement sends.

Each Slack post emits one `customer_analytics_announcement_delivery` event, and each run of
the send task emits one `customer_analytics_announcement_send` event. Events go through
`ph_background_capture()` because one task posts to every channel of an announcement, and
`ph_scoped_capture()` would block on a flush after each post. Telemetry never raises into
the send.
"""

from __future__ import annotations

import re
from typing import Final, Literal

import structlog

from posthog.ph_client import ph_background_capture
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

ANNOUNCEMENT_DELIVERY_EVENT: Final = "customer_analytics_announcement_delivery"
ANNOUNCEMENT_SEND_EVENT: Final = "customer_analytics_announcement_send"

DeliveryOutcome = Literal["sent", "failed", "deferred"]

# A Slack error code or an exception class name. Anything else (for example `str(error)`)
# can carry message text, so it is replaced instead of sent.
_ERROR_CODE_PATTERN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}")
_INVALID_ERROR_CODE: Final = "invalid"


def capture_announcement_delivery(
    *,
    team_id: int,
    announcement_id: str,
    outcome: DeliveryOutcome,
    send_as: str,
    post_seconds: float,
    seconds_since_created: float,
    error_code: str | None = None,
    retry_after_seconds: float | None = None,
) -> None:
    _capture(
        team_id,
        ANNOUNCEMENT_DELIVERY_EVENT,
        {
            "announcement_id": announcement_id,
            "outcome": outcome,
            "send_as": send_as,
            "post_seconds": round(post_seconds, 3),
            "seconds_since_created": round(seconds_since_created, 3),
            "error_code": _safe_error_code(error_code),
            "retry_after_seconds": retry_after_seconds,
        },
    )


def capture_announcement_send(
    *,
    team_id: int,
    announcement_id: str,
    attempt: int,
    status: str,
    total_channels: int,
    sent_count: int,
    failed_count: int,
    posted: int,
    deferred: int,
    interrupted: int,
    duration_seconds: float,
    seconds_to_finish: float | None = None,
    error_code: str | None = None,
) -> None:
    _capture(
        team_id,
        ANNOUNCEMENT_SEND_EVENT,
        {
            "announcement_id": announcement_id,
            "attempt": attempt,
            "is_retry": attempt > 1,
            "status": status,
            "total_channels": total_channels,
            "sent_count": sent_count,
            "failed_count": failed_count,
            "posted": posted,
            "deferred": deferred,
            "interrupted": interrupted,
            "duration_seconds": round(duration_seconds, 3),
            "seconds_to_finish": None if seconds_to_finish is None else round(seconds_to_finish, 3),
            "error_code": _safe_error_code(error_code),
        },
    )


def _capture(team_id: int, event: str, properties: dict[str, object]) -> None:
    try:
        ph_background_capture()(
            distinct_id=f"customer_analytics_announcement_team_{team_id}",
            event=event,
            properties={
                "$process_person_profile": False,
                "team_id": team_id,
                # The capture client's `region` super property overrides an event property of
                # the same name, so the deployment goes under its own key.
                "instance_region": get_instance_region() or "unknown",
                **{key: value for key, value in properties.items() if value is not None},
            },
        )
    except Exception as error:
        logger.warning("announcement_event_capture_failed", event=event, error_type=type(error).__name__)


def _safe_error_code(error_code: str | None) -> str | None:
    if error_code is None:
        return None
    return error_code if _ERROR_CODE_PATTERN.fullmatch(error_code) else _INVALID_ERROR_CODE
