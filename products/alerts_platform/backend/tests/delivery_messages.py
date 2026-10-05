from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from products.alerts_platform.backend.delivery.message import AlertMessage, MessageDetail
from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition

EPISODE_STARTED = datetime(2026, 9, 30, 9, tzinfo=UTC)
OCCURRED = datetime(2026, 9, 30, 10, tzinfo=UTC)


def announced_transition(kind: AlertEventKind = AlertEventKind.FIRING, **overrides: Any) -> AnnouncedTransition:
    fields: dict[str, Any] = {
        "grouping_key": "",
        "kind": kind,
        "episode_started_at": EPISODE_STARTED,
        "value": 300.0,
        "labels": {},
        "condition": {},
        "source_config": {},
        "error_message": None,
        "occurred_at": OCCURRED,
    }
    fields.update(overrides)
    return AnnouncedTransition(**fields)


def alert_message(
    headline: str = "API errors is firing",
    details: tuple[MessageDetail, ...] = (),
    transition: AnnouncedTransition | None = None,
    alert_name: str = "API errors",
) -> AlertMessage:
    return AlertMessage(
        headline=headline,
        details=details,
        configuration_id="cfg-1",
        alert_name=alert_name,
        transition=transition or announced_transition(),
    )


@contextmanager
def pinned_post(status: int = 200, error: Exception | None = None) -> Iterator[MagicMock]:
    session = MagicMock()
    if error:
        session.post.side_effect = error
    else:
        session.post.return_value.status_code = status
    with patch("products.alerts_platform.backend.delivery.webhook_url.pinned_session") as pinned_session:
        pinned_session.return_value.__enter__.return_value = session
        yield session
