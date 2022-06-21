import uuid
from typing import List, Optional

import structlog

from posthog.email import EmailMessage
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription, get_unsubscribe_token
from posthog.tasks.subscriptions.subscription_utils import UTM_TAGS_BASE
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


def send_email_subscription_report(
    email: str,
    subscription: Subscription,
    assets: List[ExportedAsset],
    invite_message: Optional[str] = None,
    total_asset_count: Optional[int] = None,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"

    inviter = subscription.created_by
    is_invite = invite_message is not None
    self_invite = inviter.email == email

    subject = "Posthog Report"
    resource_noun = None
    resource_url = None

    if subscription.insight:
        resource_name = f"{subscription.insight.name or subscription.insight.derived_name}"
        resource_noun = "Insight"
        resource_url = subscription.insight.url
    elif subscription.dashboard:
        resource_name = subscription.dashboard.name
        resource_noun = "Dashboard"
        resource_url = subscription.dashboard.url
    else:
        raise NotImplementedError()

    subject = f"PostHog {resource_noun} report - {resource_name}"
    campaign_key = f"{resource_noun.lower()}_subscription_report_{subscription.next_delivery_date.isoformat()}"

    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    if is_invite:
        if self_invite:
            subject = f"You have been subscribed to a PostHog {resource_noun}"
        else:
            subject = f"{inviter.first_name or 'Someone'} subscribed you to a PostHog {resource_noun}"
        campaign_key = f"{resource_noun.lower()}_subscription_new_{uuid.uuid4()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_report",
        template_context={
            "images": [x.get_public_content_url() for x in assets],
            "resource_noun": resource_noun,
            "resource_name": resource_name,
            "resource_url": f"{resource_url}?{utm_tags}",
            "subscription_url": f"{subscription.url}?{utm_tags}",
            "unsubscribe_url": unsubscribe_url,
            "inviter": inviter if is_invite else None,
            "self_invite": self_invite,
            "invite_message": invite_message,
            "total_asset_count": total_asset_count,
        },
    )
    message.add_recipient(email=email)
    message.send()
