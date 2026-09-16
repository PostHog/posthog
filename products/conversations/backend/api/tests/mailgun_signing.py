"""Signing a Mailgun route delivery the way Mailgun does, for the email endpoint tests.

The endpoints verify through `posthog/ingress/`, which reads the signature out of the form and
refuses a timestamp outside a 5 minute window. So a test drives the real route rather than
stubbing the verifier, and posts a freshly signed form each time.
"""

import hmac
import time
import hashlib
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from unittest.mock import patch

from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from posthog.ingress.contracts import WebhookDelivery
from posthog.ingress.mailgun.provider import FILES_KEY

from products.conversations.backend.services.mailgun_events import SENDER_STATUS_ABSENT

MAILGUN_SIGNING_KEY = "mailgun-signing-key"
_SIGNING_KEY_SETTING = "CONVERSATIONS_EMAIL_WEBHOOK_SIGNING_KEY"
# The transport behind the cross-region sender lookup, which a test patches to choose the answer.
SENDER_STATUS_REQUEST = "products.conversations.backend.services.mailgun_events.requests.post"


def _instance_setting(name: str) -> str:
    return MAILGUN_SIGNING_KEY if name == _SIGNING_KEY_SETTING else ""


def signed_mailgun_fields() -> dict[str, str]:
    """A fresh signature triple, with the token Mailgun mints per delivery.

    The token is the delivery id ingress dedups on, so it has to be new for every post: a real
    redelivery reuses it, and no test here is exercising a redelivery.
    """
    timestamp = str(int(time.time()))
    token = uuid4().hex
    signature = hmac.new(
        key=MAILGUN_SIGNING_KEY.encode("utf-8"),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return {"timestamp": timestamp, "token": token, "signature": signature}


def post_mailgun(client: Client, path: str, data: dict[str, Any]) -> Any:
    return client.post(path, {**signed_mailgun_fields(), **data})


def mailgun_delivery(fields: dict[str, Any], *, app: str = "inbound") -> WebhookDelivery:
    """What the provider hands a consumer for one route delivery, for a test that reads fields."""
    payload: dict[str, Any] = {**signed_mailgun_fields(), **fields}
    payload.setdefault(FILES_KEY, {})
    return WebhookDelivery(
        provider="mailgun",
        app=app,
        delivery_id=payload["token"],
        event_type="message_received",
        payload=payload,
        received_at=timezone.now(),
        context={},
    )


class MailgunWebhookTestMixin:
    """Gives a test class a signing key the endpoints verify against, and an empty dedup cache.

    The outbound path asks the other region whether it also holds the sender. That is the only
    outbound call the service makes, and it answers "no" here, so a test that is not about the
    cross-region check reaches ingestion. A test that is about it patches the same target.
    """

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        signing_key = patch(
            "products.conversations.backend.mailgun.get_instance_setting",
            side_effect=_instance_setting,
        )
        signing_key.start()
        self.addCleanup(signing_key.stop)  # type: ignore[attr-defined]

        sender_status = patch(
            SENDER_STATUS_REQUEST,
            return_value=SimpleNamespace(status_code=SENDER_STATUS_ABSENT),
        )
        sender_status.start()
        self.addCleanup(sender_status.stop)  # type: ignore[attr-defined]
        cache.clear()
