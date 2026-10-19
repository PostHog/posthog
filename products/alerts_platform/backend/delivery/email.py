"""Email delivery, to the people subscribed to an alert.

The addresses arrive resolved. The product that owns the subscriptions applies its access rules
before the platform sees an address. Sending goes through `posthog.email`, which records every
recipient against a campaign key, so a retried delivery sends nobody a second copy.

An email starts no conversation, so a send returns no handle and a resolve is a new email.
"""

from typing import Final

from django.core.exceptions import ImproperlyConfigured

from posthog.email import EmailMessage

from products.alerts_platform.backend.delivery.message import AlertMessage, transition_delivery_key
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.delivery.wire import credential_digest
from products.alerts_platform.backend.facade.contracts import AlertDestinationData

PROVIDER: Final = "email"
TEMPLATE_NAME: Final = "alert_platform_notification"


def subject_for(message: AlertMessage) -> str:
    # The alert name is user-written, and a header cannot carry a line break.
    return f"PostHog alert: {' '.join(message.headline.split())}"


class EmailTransport:
    provider = PROVIDER

    def channel_target(self, target: AlertDestinationData) -> str:
        # A digest rather than the addresses, which the thread row would otherwise store.
        return credential_digest("\n".join(sorted(target.get("email_addresses", []))))

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        addresses = target.get("email_addresses") or []
        if not addresses:
            raise DeliveryError("This email destination has no recipients.")
        try:
            email = EmailMessage(
                campaign_key=transition_delivery_key(message),
                template_name=TEMPLATE_NAME,
                subject=subject_for(message),
                template_context={
                    "headline": message.headline,
                    "details": [{"label": detail.label, "value": detail.value} for detail in message.details],
                },
            )
        except ImproperlyConfigured as error:
            raise DeliveryError("Email is not configured where this alert is delivered from.") from error
        for address in addresses:
            email.add_recipient(email=address)
        email.send()
        return None
