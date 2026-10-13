"""AWS SNS HTTPS subscriptions.

The event type is the SNS envelope's `Type`, so a consumer registers separately for the
subscription handshake and for notifications: confirming a subscription means calling AWS
back, which is the consumer's business, not the transport's.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider, require_known_app
from posthog.ingress.verify.schemes import SignatureScheme, SnsSignature

SNS_EVENT_TYPES = frozenset({"SubscriptionConfirmation", "Notification", "UnsubscribeConfirmation"})

SPECS = (ProviderSpec(provider="sns", app="default", event_types=SNS_EVENT_TYPES),)


def topic_arns_from_setting(setting_name: str) -> frozenset[str]:
    """The topics one endpoint accepts. Read per request, so an override takes effect at once."""
    return frozenset(arn for arn in getattr(settings, setting_name, ()) or () if arn)


class SnsProvider(WebhookProvider):
    provider = "sns"
    # An SNS endpoint is a public URL with no allowlisted topic until an operator sets one, so an
    # unconfigured one answers like a route that was never registered rather than confirming it
    # exists with a 500 a prober can flood the error logs with.
    unconfigured_status = 404
    # A body naming the reason would hand back the existence the 404 above withholds.
    explains_rejections = False
    # SNS retries a delivery on a non-2xx, and a subscription whose confirmation callback failed
    # stays unconfirmed until one is retried, so an unaccepted delivery must not be receipted.
    retry_status = 502

    def __init__(self, *, app: str = "default", topic_arns_setting: str) -> None:
        require_known_app(self.provider, app, SPECS)
        self.app = app
        self._scheme = SnsSignature(allowed_topic_arns=lambda: topic_arns_from_setting(topic_arns_setting))

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        message_id = payload.get("MessageId")
        topic_arn = payload.get("TopicArn")
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=str(message_id) if isinstance(message_id, str) and message_id else None,
                event_type=str(payload.get("Type", "")),
                payload=payload,
                received_at=timezone.now(),
                context={"topic_arn": str(topic_arn)} if isinstance(topic_arn, str) else {},
            ),
        )


def build_sns_provider(*, topic_arns_setting: str, app: str = "default") -> SnsProvider:
    """The topic allowlist belongs to whoever owns the topic, so the URLconf names its setting."""
    return SnsProvider(app=app, topic_arns_setting=topic_arns_setting)
