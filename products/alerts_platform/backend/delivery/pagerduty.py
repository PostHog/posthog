"""PagerDuty delivery, as Events API v2 trigger and resolve events.

PagerDuty holds an incident open until it receives a resolve with the trigger's `dedup_key`, so
this transport sends only incident actions, never messages. The dedup key names one firing
episode of one group, which is how a resolve finds the incident its trigger opened.

The routing key is the credential, and it travels in the body. It never reaches an error message,
a log line or a metric label, and the thread store keys on a digest of it.

These sends do not go through `posthog/egress`. The routing key belongs to the customer's own
PagerDuty account, and PagerDuty limits events per integration key, so no PostHog-wide budget
models it. A 429 fails the send, and the activity's retry backs off.
"""

import json
import hashlib
from typing import Any, Final

import requests

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.delivery.webhook import rfc3339
from products.alerts_platform.backend.delivery.webhook_url import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    IncidentAction,
    PagerDutyRegion,
    PagerDutySeverity,
)

PROVIDER: Final = "pagerduty"

ENDPOINTS: Final[dict[PagerDutyRegion, str]] = {
    PagerDutyRegion.US: "https://events.pagerduty.com/v2/enqueue",
    PagerDutyRegion.EU: "https://events.eu.pagerduty.com/v2/enqueue",
}

# Names the framework that sent an event, because a team on the pilot also receives the
# HogFunction path's incident for the same firing.
SOURCE: Final = "PostHog alerts platform"

_MAX_SUMMARY_LENGTH: Final = 1024
_MAX_DEDUP_KEY_LENGTH: Final = 255


def dedup_key(message: AlertMessage) -> str:
    """One firing episode of one group, so its trigger and its resolve address the same incident.

    A firing that began before the platform recorded starts has no known start. Its resolve then
    addresses an incident the platform never opened, which PagerDuty ignores.
    """
    transition = message.transition
    episode = rfc3339(transition.episode_started_at) if transition.episode_started_at else "unknown"
    key = f"{message.configuration_id}:{transition.grouping_key}:{episode}"
    if len(key) <= _MAX_DEDUP_KEY_LENGTH:
        return key
    return f"{message.configuration_id}:{hashlib.sha256(key.encode()).hexdigest()}"


def pagerduty_body(message: AlertMessage, *, routing_key: str, severity: PagerDutySeverity) -> dict[str, Any]:
    if message.incident_action is None:
        raise DeliveryError("A PagerDuty destination receives only incident events.")
    body: dict[str, Any] = {
        "routing_key": routing_key,
        "event_action": message.incident_action.value,
        "dedup_key": dedup_key(message),
    }
    if message.incident_action == IncidentAction.RESOLVE:
        return body
    transition = message.transition
    body["client"] = "PostHog"
    body["payload"] = {
        "summary": message.headline[:_MAX_SUMMARY_LENGTH],
        "source": SOURCE,
        "severity": severity.value,
        "timestamp": rfc3339(transition.occurred_at),
        "custom_details": {
            **{detail.label: detail.value for detail in message.details},
            "delivered_by": SOURCE,
            "configuration_id": message.configuration_id,
        },
    }
    return body


class PagerDutyTransport:
    provider = PROVIDER

    def channel_target(self, target: AlertDestinationData) -> str:
        # A digest rather than the key, so the thread row never stores the credential. A changed
        # key gives a new digest, so a repointed destination starts a new incident.
        return hashlib.sha256(target.get("pagerduty_routing_key", "").encode()).hexdigest()

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        routing_key = target.get("pagerduty_routing_key")
        if not routing_key:
            raise DeliveryError("This PagerDuty destination has no integration key.")
        try:
            region = PagerDutyRegion(target.get("pagerduty_region") or PagerDutyRegion.US)
            severity = PagerDutySeverity(target.get("pagerduty_severity") or PagerDutySeverity.ERROR)
        except ValueError:
            raise DeliveryError("This PagerDuty destination has an unknown region or severity.") from None
        self._post(ENDPOINTS[region], pagerduty_body(message, routing_key=routing_key, severity=severity))
        # PagerDuty answers with the dedup key, which this transport derives again for the resolve.
        return None

    def _post(self, url: str, body: dict[str, Any]) -> None:
        try:
            response = requests.post(
                url,
                data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise DeliveryError(f"PagerDuty could not be reached: {type(error).__name__}") from None
        if not 200 <= response.status_code < 300:
            # The status only. A 400's body can quote the event, and the event holds the routing key.
            raise DeliveryError(f"PagerDuty refused the event with status {response.status_code}.")
