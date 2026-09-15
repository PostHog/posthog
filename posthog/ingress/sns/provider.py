"""AWS SNS HTTPS subscriptions.

The event type is the SNS envelope's `Type`, so a consumer registers separately for the
subscription handshake and for notifications: confirming a subscription means calling AWS
back, which is the consumer's business, not the transport's.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import SignatureScheme, SnsSignature

SNS_EVENT_TYPES = frozenset({"SubscriptionConfirmation", "Notification", "UnsubscribeConfirmation"})

SPECS = (ProviderSpec(provider="sns", app="default", event_types=SNS_EVENT_TYPES),)


class SnsProvider(WebhookProvider):
    provider = "sns"

    def __init__(
        self,
        *,
        app: str = "default",
        verify_message: Callable[[Mapping[str, Any]], bool],
        allowed_topic_arns: Callable[[], frozenset[str]],
    ) -> None:
        self.app = app
        self._scheme = SnsSignature(verify_message=verify_message, allowed_topic_arns=allowed_topic_arns)

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any) -> Sequence[WebhookDelivery]:
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


def build_sns_provider(
    *,
    verify_message: Callable[[Mapping[str, Any]], bool],
    allowed_topic_arns: Callable[[], frozenset[str]],
    app: str = "default",
) -> SnsProvider:
    """The RSA verifier and the topic allowlist belong to whoever owns the topic, so both are
    passed in rather than reached for from here."""
    return SnsProvider(app=app, verify_message=verify_message, allowed_topic_arns=allowed_topic_arns)
