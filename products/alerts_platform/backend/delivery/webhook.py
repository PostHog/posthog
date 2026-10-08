"""Generic webhook delivery, as an Alertmanager webhook body (version 4).

Incident and on-call tools accept that body without a custom parser, which is why it replaces
the per-source bodies the HogFunction path sends. One message carries one alert, because one
transition is one message.
"""

import hashlib
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

from django.conf import settings

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.delivery.webhook_url import WebhookUrlTransport
from products.alerts_platform.backend.delivery.wire import rfc3339
from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition

PROVIDER: Final = "webhook"

# The HogFunction path sends version 1, which is a different body. A receiver that gets both
# while a team is on the pilot tells them apart by this header.
WEBHOOK_VERSION: Final = "2"

# What Alertmanager sends as the end of an alert that has not resolved.
_NOT_ENDED: Final = "0001-01-01T00:00:00Z"

_BREACH_KINDS: Final = (AlertEventKind.FIRING, AlertEventKind.RESOLVED)


def _fingerprint(configuration_id: str, transition: AnnouncedTransition) -> str:
    # A failed or a turned-off check is a separate alert to a receiver. With the breach's
    # fingerprint, the breach's resolve would close it, and a later breach would read as an
    # alert that is already open.
    series = "breach" if transition.kind in _BREACH_KINDS else transition.kind.value
    return hashlib.sha256(f"{configuration_id}|{transition.grouping_key}|{series}".encode()).hexdigest()[:16]


def _annotations(message: AlertMessage) -> dict[str, str]:
    annotations = {"summary": message.headline}
    if message.details:
        annotations["description"] = "\n".join(f"{detail.label}: {detail.value}" for detail in message.details)
    if message.transition.value is not None:
        annotations["value"] = f"{message.transition.value:g}"
    if message.transition.error_message:
        annotations["error"] = message.transition.error_message
    return annotations


def alertmanager_body(message: AlertMessage) -> dict[str, Any]:
    transition = message.transition
    configuration_id = message.configuration_id
    # Alertmanager has only these two statuses. A failed or a turned-off check goes out as
    # firing, and `posthog_event_kind` is what tells it apart from a breach.
    status = "resolved" if transition.kind == AlertEventKind.RESOLVED else "firing"
    group_labels = {"alertname": message.alert_name, "posthog_configuration_id": configuration_id}
    # The platform's own labels come last, so a source label with the same name cannot replace them.
    labels = {**transition.labels, **group_labels, "posthog_event_kind": transition.kind.value}
    annotations = _annotations(message)
    return {
        "version": "4",
        "groupKey": f"{configuration_id}:{transition.grouping_key}",
        "truncatedAlerts": 0,
        "status": status,
        "receiver": "posthog",
        "groupLabels": group_labels,
        "commonLabels": labels,
        "commonAnnotations": annotations,
        "externalURL": settings.SITE_URL,
        "alerts": [
            {
                "status": status,
                "labels": labels,
                "annotations": annotations,
                "startsAt": rfc3339(transition.episode_started_at or transition.occurred_at),
                "endsAt": rfc3339(transition.occurred_at) if status == "resolved" else _NOT_ENDED,
                "generatorURL": "",
                "fingerprint": _fingerprint(configuration_id, transition),
            }
        ],
    }


class WebhookTransport(WebhookUrlTransport):
    provider = PROVIDER
    display_name = "webhook"
    headers: ClassVar[dict[str, str]] = {"X-PostHog-Webhook-Version": WEBHOOK_VERSION}

    def check_url(self, url: str) -> None:
        # Plain HTTP would expose the URL, which is the credential, and the alert body to anyone on
        # the path. Teams and Discord URLs are always HTTPS, so only the generic webhook needs this.
        if urlsplit(url).scheme != "https":
            raise DeliveryError("This webhook destination's URL must use https.")

    def body_for(self, message: AlertMessage) -> dict[str, Any]:
        return alertmanager_body(message)
