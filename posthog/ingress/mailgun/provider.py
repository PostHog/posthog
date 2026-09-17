"""Mailgun route deliveries: a mail message posted as a form, and signed inside that form.

Mailgun never posts JSON to a route. It posts an urlencoded or a multipart form, and it puts
the three signature fields in the same form as the message. So `verify` and `parse` both read
`request.POST` rather than `request.body`: a multipart body is consumed by the form parser, and
the raw bytes are no longer available afterwards.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, QueryDict, UnreadablePostError
from django.http.multipartparser import MultiPartParserError
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import InvalidPayload, WebhookProvider
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme, Verification, VerificationOutcome

# These go to the HMAC scheme as header names, because the scheme reads a mapping and does not
# care where the caller found it.
SIGNATURE_FIELD = "signature"
TIMESTAMP_FIELD = "timestamp"
TOKEN_FIELD = "token"

# A route carries a message rather than an event, so there is no event field to read and the app
# decides the event type.
_APP_EVENT_TYPES: Mapping[str, str] = {
    "inbound": "message_received",
    "outbound": "message_sent",
}

SPECS = tuple(
    ProviderSpec(provider="mailgun", app=app, event_types=frozenset({event_type}))
    for app, event_type in _APP_EVENT_TYPES.items()
)

_FORM_CONTENT_TYPES = frozenset({"application/x-www-form-urlencoded", "multipart/form-data"})

# A consumer must read these inside the request. An UploadedFile is backed by the request stream
# or a temporary file, so it does not survive the response and cannot be handed to a task.
FILES_KEY = "_files"

# Bounds what a consumer iterates, not what the request costs: the form parser reads and spools
# every part before this code runs, and DATA_UPLOAD_MAX_NUMBER_FILES is what bounds that.
MAX_FILES = 20


def _files_in_request(request: HttpRequest) -> dict[str, UploadedFile]:
    return {name: cast(UploadedFile, request.FILES[name]) for name in list(request.FILES)[:MAX_FILES]}


class MailgunProvider(WebhookProvider):
    provider = "mailgun"
    # A route delivery carries the whole mail message, including up to MAX_FILES attachments, and
    # the forward rebuilds and re-sends every part. Three seconds is not enough for that.
    forward_timeout_seconds = 10.0

    def __init__(self, app: str, *, signing_key_getter: Callable[[], str | None]) -> None:
        event_type = _APP_EVENT_TYPES.get(app)
        if event_type is None:
            raise ValueError(f"Unknown Mailgun app {app!r}, expected one of {sorted(_APP_EVENT_TYPES)}")
        self.app = app
        self.event_type = event_type
        self._scheme = HmacSha256(
            secret_getter=signing_key_getter,
            signature_header=SIGNATURE_FIELD,
            timestamp_header=TIMESTAMP_FIELD,
        )

    def _form(self, request: HttpRequest) -> QueryDict | None:
        if request.content_type not in _FORM_CONTENT_TYPES:
            return None
        try:
            return request.POST
        except (MultiPartParserError, UnreadablePostError):
            # A truncated or malformed multipart body is the caller's problem, so it must not
            # become a 500. Django answers RequestDataTooBig and TooManyFieldsSent itself.
            return None

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def verify(self, request: HttpRequest) -> Verification:
        form = self._form(request)
        if form is None:
            return Verification(outcome=VerificationOutcome.INVALID)
        timestamp = form.get(TIMESTAMP_FIELD, "")
        token = form.get(TOKEN_FIELD, "")
        # Mailgun signs the concatenation of the timestamp and the token, not the body.
        return self._scheme.verify(
            body=f"{timestamp}{token}".encode(),
            headers={SIGNATURE_FIELD: form.get(SIGNATURE_FIELD, ""), TIMESTAMP_FIELD: timestamp},
        )

    def parse(self, request: HttpRequest) -> Any:
        form = self._form(request)
        if form is None:
            raise InvalidPayload(f"expected a form body, got content type {request.content_type!r}")
        # Django caches the parsed form, so this second read costs nothing.
        payload: dict[str, Any] = form.dict()
        payload[FILES_KEY] = _files_in_request(request)
        return payload

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        token = payload.get(TOKEN_FIELD)
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                # Mailgun mints a fresh token per delivery, so it keys dedup on its own.
                delivery_id=str(token) if token else None,
                event_type=self.event_type,
                payload=payload,
                received_at=timezone.now(),
                context={},
            ),
        )


def build_mailgun_provider(app: str, *, signing_key_getter: Callable[[], str | None]) -> MailgunProvider:
    return MailgunProvider(app, signing_key_getter=signing_key_getter)
