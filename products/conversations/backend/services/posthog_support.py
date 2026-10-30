"""Client for PostHog's own support inbox, for a signed-in user's agent.

Requests go to the support project's public widget API, the same API the in-app support panel
calls. The server signs the user's identity with the HMAC the web app embeds for that panel, so
tickets arrive verified and the caller never holds a signing value.
"""

import time
from typing import Any

from django.conf import settings

import requests
import structlog

from posthog.constants import POSTHOG_JS_CLOUD_HOST
from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting

from products.conversations.backend.services.identity import (
    IDENTITY_CLAIM_MAX_AGE_SECONDS,
    canonicalize_claim_value,
    compute_identity_claim_hash,
    compute_identity_hash,
)

logger = structlog.get_logger(__name__)

WIDGET_REQUEST_TIMEOUT_SECONDS = 10


class PostHogSupportUnavailable(Exception):
    """The instance has no support project configured, as on self-hosted deployments."""


class PostHogSupportRequestFailed(Exception):
    def __init__(self, status_code: int | None) -> None:
        super().__init__(f"Support widget request failed with status {status_code}")
        self.status_code = status_code


@frozen
class SupportIdentity:
    distinct_id: str
    # Only a verified address: the support inbox trusts it to join tickets from other channels.
    verified_email: str | None


class PostHogSupportClient:
    def __init__(self, *, token: str, host: str, signing_secret: str) -> None:
        self._token = token
        self._host = host.rstrip("/")
        self._signing_secret = signing_secret

    @classmethod
    def from_settings(cls) -> "PostHogSupportClient":
        token = get_instance_setting("CONVERSATIONS_SUPPORT_WIDGET_TOKEN")
        signing_secret = get_instance_setting("CONVERSATIONS_HMAC_SIGNING_SECRET")
        if not token or not signing_secret:
            raise PostHogSupportUnavailable()
        host = get_instance_setting("CONVERSATIONS_SUPPORT_WIDGET_HOST") or POSTHOG_JS_CLOUD_HOST
        return cls(token=token, host=host, signing_secret=signing_secret)

    def create_ticket(
        self,
        identity: SupportIdentity,
        *,
        message: str,
        traits: dict[str, str],
        session_context: dict[str, str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            **self._identity_fields(identity),
            "message": message,
            "traits": traits,
            "session_context": session_context,
        }
        return self._request("POST", "/api/conversations/v1/widget/message", json=payload)

    def _identity_fields(self, identity: SupportIdentity) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "identity_distinct_id": identity.distinct_id,
            "identity_hash": compute_identity_hash(identity.distinct_id, self._signing_secret),
        }
        if identity.verified_email:
            email = canonicalize_claim_value("email", identity.verified_email)
            expires_at = int(time.time()) + IDENTITY_CLAIM_MAX_AGE_SECONDS
            fields["identity_email"] = email
            fields["identity_exp_email"] = expires_at
            fields["identity_hash_email"] = compute_identity_claim_hash(
                identity.distinct_id, "email", email, self._signing_secret, expires_at=expires_at
            )
        return fields

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {
            "X-Conversations-Token": self._token,
            # The support project can limit widget requests to its own domains. This request
            # stands in for the support panel of this instance, so it carries this instance's origin.
            "Origin": settings.SITE_URL,
        }
        try:
            response = requests.request(
                method,
                f"{self._host}{path}",
                headers=headers,
                timeout=WIDGET_REQUEST_TIMEOUT_SECONDS,
                **kwargs,
            )
        except requests.RequestException as e:
            logger.warning("posthog_support_request_error", path=path, error=type(e).__name__)
            raise PostHogSupportRequestFailed(None) from e
        if not response.ok:
            logger.warning("posthog_support_request_rejected", path=path, status_code=response.status_code)
            raise PostHogSupportRequestFailed(response.status_code)
        return response.json()
