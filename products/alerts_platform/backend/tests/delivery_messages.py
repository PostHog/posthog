import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from unittest.mock import patch

from requests import PreparedRequest, Response, Session
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from products.alerts_platform.backend.delivery.message import AlertMessage, MessageDetail
from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition, IncidentAction

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
    incident_action: IncidentAction | None = None,
) -> AlertMessage:
    return AlertMessage(
        headline=headline,
        details=details,
        configuration_id="cfg-1",
        alert_name=alert_name,
        transition=transition or announced_transition(),
        incident_action=incident_action,
    )


class UnreadBody(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.bytes_read = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


class RecordingAdapter(BaseAdapter):
    def __init__(self, status: int, error: Exception | None, headers: dict[str, str], body: bytes) -> None:
        super().__init__()
        self.status = status
        self.error = error
        self.headers = headers
        self.body = UnreadBody(body)
        self.sent: list[PreparedRequest] = []

    def send(self, request: PreparedRequest, *args: Any, **kwargs: Any) -> Response:
        self.sent.append(request)
        if self.error:
            raise self.error
        response = Response()
        response.status_code = self.status
        response.headers = CaseInsensitiveDict(self.headers)
        response.raw = self.body
        response.url = request.url or ""
        response.request = request
        return response

    def close(self) -> None:
        return None


@contextmanager
def pinned_post(
    status: int = 200, error: Exception | None = None, headers: dict[str, str] | None = None, body: bytes = b""
) -> Iterator[RecordingAdapter]:
    adapter = RecordingAdapter(status, error, headers or {}, body)
    session = Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    with patch("products.alerts_platform.backend.delivery.webhook_url.pinned_session") as pinned_session:
        pinned_session.return_value.__enter__.return_value = session
        yield adapter
