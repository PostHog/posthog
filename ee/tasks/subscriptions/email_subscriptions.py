import uuid
from typing import Optional

import structlog

from posthog.email import EmailMessage
from posthog.models.exported_asset import ExportedAsset
from posthog.models.subscription import Subscription, get_unsubscribe_token
from posthog.utils import absolute_uri

from ee.tasks.subscriptions.subscription_utils import UTM_TAGS_BASE

logger = structlog.get_logger(__name__)


def _get_asset_data_for_email(asset: ExportedAsset) -> dict:
    if asset.exception:
        insight_name = asset.insight.name or asset.insight.derived_name if asset.insight else "Unknown insight"
        return {
            "error": True,
            "insight_name": insight_name,
            "error_message": asset.exception,
        }

    return {
        "error": False,
        "image_url": asset.get_public_content_url(),
    }


def send_email_subscription_report(
    email: str,
    subscription: Subscription,
    assets: list[ExportedAsset],
    invite_message: Optional[str] = None,
    total_asset_count: Optional[int] = None,
    send_async: bool = True,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"

    inviter = subscription.created_by
    is_invite = invite_message is not None
    self_invite = inviter.email == email

    subject = "PostHog Report"
    invite_summary = None

    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    subject = f"PostHog {resource_info.kind} report - {resource_info.name}"
    campaign_key = f"{resource_info.kind.lower()}_subscription_report_{subscription.next_delivery_date.isoformat()}"

    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    if is_invite:
        invite_summary = f"This subscription is { subscription.summary }. The next subscription will be sent on { subscription.next_delivery_date.strftime('%A %B %d, %Y')}"
        if self_invite:
            subject = f"You have been subscribed to a PostHog {resource_info.kind}"
        else:
            subject = f"{inviter.first_name or 'Someone'} subscribed you to a PostHog {resource_info.kind}"
        campaign_key = f"{resource_info.kind.lower()}_subscription_new_{uuid.uuid4()}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=subject,
        template_name="subscription_report",
        template_context={
            "asset_data": [_get_asset_data_for_email(x) for x in assets],
            "resource_noun": resource_info.kind,
            "resource_name": resource_info.name,
            "resource_url": f"{resource_info.url}?{utm_tags}",
            "subscription_url": f"{subscription.url}?{utm_tags}",
            "unsubscribe_url": unsubscribe_url,
            "inviter": inviter if is_invite else None,
            "self_invite": self_invite,
            "invite_message": invite_message,
            "invite_summary": invite_summary,
            "total_asset_count": total_asset_count,
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=send_async)
