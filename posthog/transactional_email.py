from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import requests


class TransactionalEmailRetryableError(Exception):
    """The API did not accept the email, so retrying cannot duplicate it."""

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TransactionalEmailRejected(Exception):
    """The API rejected the email and requires caller intervention."""


class TransactionalEmailDeliveryUncertain(Exception):
    """The API may have accepted the email; reconcile before retrying."""


def is_transactional_email_configured() -> bool:
    return bool(
        settings.POSTHOG_HOST and settings.POSTHOG_PROJECT_ID > 0 and settings.POSTHOG_TRANSACTIONAL_EMAIL_API_KEY
    )


def _send_url(template_id: str) -> str:
    if not is_transactional_email_configured():
        raise ImproperlyConfigured("PostHog transactional email settings are missing")

    host = settings.POSTHOG_HOST.rstrip("/")
    parsed_host = urlsplit(host)
    if (
        parsed_host.scheme != "https"
        or not parsed_host.netloc
        or parsed_host.username
        or parsed_host.password
        or parsed_host.path
        or parsed_host.query
        or parsed_host.fragment
    ):
        raise ImproperlyConfigured("POSTHOG_HOST must be an HTTPS origin")
    try:
        template_uuid = UUID(template_id)
    except ValueError:
        raise ImproperlyConfigured("Transactional email template ID must be a UUID") from None
    return f"{host}/api/projects/{settings.POSTHOG_PROJECT_ID}/messaging_templates/{template_uuid}/send/"


def send_transactional_email(
    template_id: str,
    *,
    to: str,
    distinct_id: str | None = None,
    message_data: dict[str, object] | None = None,
) -> str:
    """Return the API's message ID after queue acceptance, not mailbox delivery.

    The send API has no idempotency key. Callers must not retry uncertain outcomes.
    """
    url = _send_url(template_id)

    payload: dict[str, object] = {"to": to, "message_data": message_data or {}}
    if distinct_id is not None:
        payload["identifiers"] = {"distinct_id": distinct_id}

    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {settings.POSTHOG_TRANSACTIONAL_EMAIL_API_KEY}"},
            json=payload,
            timeout=(3, 10),
            allow_redirects=False,
        )
    except requests.ConnectTimeout:
        raise TransactionalEmailRetryableError("connect_timeout") from None
    except requests.RequestException:
        # Request exceptions may retain authorization headers and response bodies.
        raise TransactionalEmailDeliveryUncertain("request_failed") from None

    if response.status_code == 429:
        try:
            retry_after: int | None = max(0, int(response.headers.get("Retry-After", "")))
        except (ValueError, TypeError):
            retry_after = None
        raise TransactionalEmailRetryableError("rate_limited", retry_after=retry_after)
    if 300 <= response.status_code < 500 and response.status_code != 408:
        raise TransactionalEmailRejected(f"http_{response.status_code}")
    if response.status_code != 202:
        raise TransactionalEmailDeliveryUncertain(f"http_{response.status_code}")

    try:
        data = response.json()
    except ValueError:
        raise TransactionalEmailDeliveryUncertain("invalid_response") from None
    message_id = data.get("message_id") if isinstance(data, dict) else None
    if not isinstance(message_id, str) or not message_id:
        raise TransactionalEmailDeliveryUncertain("invalid_response")
    return message_id
