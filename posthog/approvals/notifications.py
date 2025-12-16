from typing import TYPE_CHECKING

from django.conf import settings

from structlog import get_logger

from posthog.models import User
from posthog.models.instance_setting import get_instance_setting

if TYPE_CHECKING:
    from posthog.approvals.models import Approval, ChangeRequest

logger = get_logger(__name__)


def send_approval_requested_notification(change_request: "ChangeRequest") -> None:
    """
    Notify approvers that a new change request requires their approval.
    """
    policy = change_request.get_policy()
    if not policy:
        logger.warning(
            "send_approval_requested_notification.no_policy",
            change_request_id=str(change_request.id),
        )
        return

    approver_ids = policy.get_approver_user_ids()
    approvers = User.objects.filter(id__in=approver_ids)

    for approver in approvers:
        try:
            _send_email(
                recipient=approver,
                subject=f"Approval required: {change_request.action_key}",
                template="approval_requested",
                context={
                    "change_request": change_request,
                    "approver": approver,
                    "requester": change_request.created_by,
                    "team": change_request.team,
                },
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
    try:
        if not change_request.created_by:
            return
        decision = "approved" if approval.decision == "approved" else "rejected"
        _send_email(
            recipient=change_request.created_by,
            subject=f"Your change request was {decision}: {change_request.action_key}",
            template=f"approval_{decision}",
            context={
                "change_request": change_request,
                "approval": approval,
                "requester": change_request.created_by,
                "approver": approval.created_by,
                "team": change_request.team,
            },
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
    try:
        if not change_request.created_by:
            return
        _send_email(
            recipient=change_request.created_by,
            subject=f"Your change request expired: {change_request.action_key}",
            template="approval_expired",
            context={
                "change_request": change_request,
                "requester": change_request.created_by,
                "team": change_request.team,
            },
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
            return
        _send_email(
            recipient=change_request.created_by,
            subject=f"Your change request was applied: {change_request.action_key}",
            template="approval_applied",
            context={
                "change_request": change_request,
                "requester": change_request.created_by,
                "team": change_request.team,
            },
        )
    except Exception as e:
        logger.exception(
            "send_approval_applied_notification.error",
            change_request_id=str(change_request.id),
            error=str(e),
        )


def _send_email(
    recipient: User,
    subject: str,
    template: str,
    context: dict,
) -> None:
    """
    Send an email using PostHog's email infrastructure.
    For now, this is a placeholder - actual implementation would use
    PostHog's messaging system or email backend.
    """
    email_enabled = get_instance_setting("EMAIL_ENABLED")

    if settings.TEST or not email_enabled:
        logger.info(
            "notifications.email_skipped",
            recipient_id=recipient.id,
            subject=subject,
            template=template,
        )
        return

    # TODO: Integrate with PostHog's email system
    # This would use the messaging system or direct email backend
    logger.info(
        "notifications.email_sent",
        recipient_id=recipient.id,
        recipient_email=recipient.email,
        subject=subject,
        template=template,
    )
