from typing import TYPE_CHECKING

from structlog import get_logger

from posthog.email import EmailMessage, is_email_available
from posthog.models import User
from posthog.utils import absolute_uri

if TYPE_CHECKING:
    from posthog.approvals.models import Approval, ChangeRequest

logger = get_logger(__name__)


def _get_user_display_name(user: User | None, fallback: str = "A team member") -> str:
    """Get display name for a user, falling back to email or default."""
    if not user:
        return fallback
    return user.get_full_name() or user.email


def _build_change_request_url(change_request: "ChangeRequest") -> str:
    """Build the absolute URL to view a change request."""
    return absolute_uri(f"/project/{change_request.team.project_id}/approvals/{change_request.id}")


def _send_approval_email(
    recipient: User,
    template_name: str,
    subject: str,
    change_request: "ChangeRequest",
    extra_context: dict | None = None,
) -> None:
    if not is_email_available(with_absolute_urls=True):
        logger.info(
            "notifications.email_skipped.email_not_available",
            recipient_id=recipient.id,
            template=template_name,
        )
        return

    change_request_url = _build_change_request_url(change_request)
    campaign_key = f"approval_{template_name}_{change_request.id}_{recipient.id}"

    template_context = {
        "change_request_url": change_request_url,
        "team_name": change_request.team.name,
    }
    if extra_context:
        template_context.update(extra_context)

    try:
        message = EmailMessage(
            campaign_key=campaign_key,
            template_name=template_name,
            subject=subject,
            template_context=template_context,
            use_http=True,
        )
        message.add_user_recipient(recipient)
        message.send(send_async=True)

    except Exception as e:
        logger.exception(
            "notifications.email_error",
            recipient_id=recipient.id,
            template=template_name,
            change_request_id=str(change_request.id),
            error=str(e),
        )
        raise


def send_approval_requested_notification(change_request: "ChangeRequest") -> None:
    """
    Notify approvers that a new change request requires their approval.
    Sends one email per approver for granular retry.
    """
    policy = change_request.get_policy()
    if not policy:
        logger.warning(
            "send_approval_requested_notification.no_policy",
            change_request_id=str(change_request.id),
        )
        return

    approver_ids = policy.get_approver_user_ids()
    if not approver_ids:
        logger.info(
            "send_approval_requested_notification.no_approvers",
            change_request_id=str(change_request.id),
        )
        return

    approvers = User.objects.filter(id__in=approver_ids)
    requester_name = _get_user_display_name(change_request.created_by)

    for approver in approvers:
        try:
            _send_approval_email(
                recipient=approver,
                template_name="approval_requested",
                subject=f"{requester_name} needs your sign-off",
                change_request=change_request,
                extra_context={"requester_name": requester_name},
            )
        except Exception as e:
            logger.exception(
                "send_approval_requested_notification.error",
                change_request_id=str(change_request.id),
                approver_id=approver.id,
                error=str(e),
            )


def send_approval_decision_notification(
    change_request: "ChangeRequest",
    approval: "Approval",
) -> None:
    """
    Notify the requester that their change request was approved or rejected.
    """
    if not change_request.created_by:
        logger.info(
            "send_approval_decision_notification.no_requester",
            change_request_id=str(change_request.id),
        )
        return

    is_approved = approval.decision == "approved"
    template_name = "approval_approved" if is_approved else "approval_rejected"
    approver_name = _get_user_display_name(approval.created_by, fallback="Someone")
    subject = f"{approver_name} approved your change" if is_approved else "Your change request was declined"

    try:
        _send_approval_email(
            recipient=change_request.created_by,
            template_name=template_name,
            subject=subject,
            change_request=change_request,
            extra_context={"approver_name": approver_name},
        )
    except Exception as e:
        logger.exception(
            "send_approval_decision_notification.error",
            change_request_id=str(change_request.id),
            approval_id=str(approval.id),
            error=str(e),
        )


def send_approval_expired_notification(change_request: "ChangeRequest") -> None:
    """
    Notify the requester that their change request has expired.
    """
    if not change_request.created_by:
        logger.info(
            "send_approval_expired_notification.no_requester",
            change_request_id=str(change_request.id),
        )
        return

    try:
        _send_approval_email(
            recipient=change_request.created_by,
            template_name="approval_expired",
            subject="Your change request timed out",
            change_request=change_request,
        )
    except Exception as e:
        logger.exception(
            "send_approval_expired_notification.error",
            change_request_id=str(change_request.id),
            error=str(e),
        )


def send_approval_applied_notification(change_request: "ChangeRequest") -> None:
    """
    Notify the requester that their change request has been successfully applied.
    """
    try:
        if not change_request.created_by:
            logger.info(
                "send_approval_applied_notification.no_requester",
                change_request_id=str(change_request.id),
            )
            return

        _send_approval_email(
            recipient=change_request.created_by,
            template_name="approval_applied",
            subject="Your change is live! 🎉",
            change_request=change_request,
        )
    except Exception as e:
        logger.exception(
            "send_approval_applied_notification.error",
            change_request_id=str(change_request.id),
            error=str(e),
        )
