"""PagerDuty delivery, as Events API v2 trigger and resolve events.

PagerDuty holds an incident open until it receives a resolve with the trigger's `dedup_key`, so
this transport sends only incident actions, never messages. The dedup key names one firing
episode of one group, which is how a resolve finds the incident its trigger opened.

The routing key is the credential, and it travels in the body. It never reaches an error message,
a log line or a metric label, and the thread store keys on a digest of it.

These sends do not go through `posthog/egress`. The routing key belongs to the customer's own
PagerDuty account, and PagerDuty limits events per integration key, so no PostHog-wide budget
models it. A 429 fails the send, and the activity's retry backs off.

The thread store claims each send, so a retry of a send that already landed does not post again.
It does not order sends across evaluations: a trigger whose delivery failed and is retried after
its resolve landed reopens the incident under the same dedup key.
"""

import hashlib
from typing import Any, Final

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.delivery.wire import credential_digest, post_json, rfc3339
from products.alerts_platform.backend.facade.contracts import (
    DEFAULT_PAGERDUTY_REGION,
    DEFAULT_PAGERDUTY_SEVERITY,
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
        return credential_digest(target.get("pagerduty_routing_key", ""))

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
            region = PagerDutyRegion(target.get("pagerduty_region") or DEFAULT_PAGERDUTY_REGION)
            severity = PagerDutySeverity(target.get("pagerduty_severity") or DEFAULT_PAGERDUTY_SEVERITY)
        except ValueError:
            raise DeliveryError("This PagerDuty destination has an unknown region or severity.") from None
        body = pagerduty_body(message, routing_key=routing_key, severity=severity)
        post_json(ENDPOINTS[region], body, display_name="PagerDuty")
        # PagerDuty answers with the dedup key, which this transport derives again for the resolve.
        return None
