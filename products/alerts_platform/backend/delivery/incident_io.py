"""incident.io delivery, as events to an HTTP alert source.

https://docs.incident.io/openapi/tags/alert-events-v2.json

incident.io keeps an alert open until it receives a `resolved` event with the `deduplication_key`
of the `firing` one, so this transport sends only incident actions, never messages. The key is the
one PagerDuty gets, which names one firing episode of one group.

The alert source's secret is the credential, and it travels in the Authorization header. It never
reaches an error message, a log line or a metric label, and the thread store keys on a digest of it.
Whether an alert opens an incident is decided by the alert routes the customer configures in
incident.io, not here.
"""

from typing import Any, Final

from products.alerts_platform.backend.delivery.discord import escape_markdown
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.pagerduty import dedup_key
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.delivery.wire import credential_digest, post_json
from products.alerts_platform.backend.facade.contracts import (
    INCIDENT_IO_ALERT_SOURCE_CONFIG_ID_RE,
    AlertDestinationData,
    IncidentAction,
)

PROVIDER: Final = "incident_io"

_STATUSES: Final[dict[IncidentAction, str]] = {
    IncidentAction.TRIGGER: "firing",
    IncidentAction.RESOLVE: "resolved",
}

# A wrong secret or a deleted alert source. Each is the owner's to fix, and every retry fails the same way.
_OWNER_REFUSALS: Final[dict[int, bytes | None]] = {401: None, 403: None, 404: None}


def endpoint(alert_source_config_id: str) -> str:
    return f"https://api.incident.io/v2/alert_events/http/{alert_source_config_id}"


def incident_io_body(message: AlertMessage) -> dict[str, Any]:
    if message.incident_action is None:
        raise DeliveryError("An incident.io destination receives only incident events.")
    body: dict[str, Any] = {
        "title": message.headline,
        "status": _STATUSES[message.incident_action],
        "deduplication_key": dedup_key(message),
        "source_url": message.alert_url,
        # incident.io alert routes filter and pick escalation paths on these, so they carry the labels PostHog
        # routes match on. The platform's own keys come last, so a label with the same name cannot replace them.
        "metadata": {
            **message.labels,
            "posthog_configuration_id": message.configuration_id,
            "posthog_source_kind": message.source.value,
        },
    }
    details = (*message.details, *message.rule_details)
    if details:
        # A value can come from ingested data, such as a log's service name, so it must not render as a link.
        body["description"] = "\n".join(f"**{detail.label}:** {escape_markdown(detail.value)}" for detail in details)
    return body


class IncidentIoTransport:
    provider = PROVIDER

    def channel_target(self, target: AlertDestinationData) -> str:
        return credential_digest(
            target.get("incident_io_alert_source_config_id", "") + "\n" + target.get("incident_io_secret", "")
        )

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        config_id = target.get("incident_io_alert_source_config_id") or ""
        secret = target.get("incident_io_secret")
        if not INCIDENT_IO_ALERT_SOURCE_CONFIG_ID_RE.fullmatch(config_id) or not secret:
            raise DeliveryError("This incident.io destination has no valid alert source ID or secret.")
        post_json(
            endpoint(config_id),
            incident_io_body(message),
            display_name="incident.io",
            headers={"Authorization": f"Bearer {secret}"},
            owner_refusals=_OWNER_REFUSALS,
        )
        # incident.io answers with the deduplication key, which this transport derives again for the resolve.
        return None
