from typing import Any

from django.db import transaction
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.approvals.models import ChangeRequest, ChangeRequestState, ValidationStatus
from posthog.approvals.notifications import send_approval_expired_notification
from posthog.scoping_audit import skip_team_scope_audit

logger = get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def validate_pending_change_requests() -> dict[str, Any]:
    """
    Periodic staleness check for pending change requests.

    Compares stored preconditions against the current resource state.
    Marks CRs as STALE when the underlying resource has been modified,
    which allows requesters to cancel even after approvals have been given.
    """
    stale_count = 0
    checked_count = 0
    errors: list[str] = []

    pending_requests = ChangeRequest.objects.filter(
        state=ChangeRequestState.PENDING,
    ).exclude(validation_status=ValidationStatus.STALE)

    for change_request in pending_requests:
        try:
            action_class = change_request.get_action_class()
            if not action_class:
                logger.warning(
                    "validate_pending_change_requests.no_action_class",
                    change_request_id=str(change_request.id),
                    action_key=change_request.action_key,
                )
                continue

            checked_count += 1

            base_context = {
                "team": change_request.team,
                "team_id": change_request.team_id,
                "organization": change_request.organization,
            }
            context = action_class.prepare_context(change_request, base_context)

            if action_class.check_staleness(change_request.intent, context):
                change_request.validation_status = ValidationStatus.STALE
                change_request.validation_errors = {
                    "staleness": "Resource has been modified since this change request was created"
                }
                change_request.validated_at = timezone.now()
                change_request.save(update_fields=["validation_status", "validation_errors", "validated_at"])
                stale_count += 1
                logger.info(
                    "validate_pending_change_requests.stale",
                    change_request_id=str(change_request.id),
                )

        except Exception as e:
            error_msg = f"Error validating change request {change_request.id}: {str(e)}"
            errors.append(error_msg)
            logger.exception(
                "validate_pending_change_requests.error",
                change_request_id=str(change_request.id),
                error=str(e),
            )

    result = {
        "checked_count": checked_count,
        "stale_count": stale_count,
        "errors": errors,
    }

    logger.info("validate_pending_change_requests.complete", **result)
    return result


@shared_task(ignore_result=True)
@skip_team_scope_audit
def expire_old_change_requests() -> dict[str, Any]:
    """
    Scheduled task to expire old pending change requests.

    Runs hourly via Celery beat.
    """
    now = timezone.now()
    expired_count = 0
    errors: list[str] = []

    pending_requests = ChangeRequest.objects.filter(
        state__in=[ChangeRequestState.PENDING, ChangeRequestState.APPROVED],
        expires_at__lte=now,
    )

    for change_request in pending_requests:
        try:
            with transaction.atomic():
                locked_cr = ChangeRequest.objects.select_for_update().get(pk=change_request.pk)
                if locked_cr.state not in (ChangeRequestState.PENDING, ChangeRequestState.APPROVED):
                    continue

                locked_cr.state = ChangeRequestState.EXPIRED
                locked_cr.save(update_fields=["state"])

            expired_count += 1

            logger.info(
                "expire_old_change_requests.expired",
                change_request_id=str(change_request.id),
                action_key=change_request.action_key,
                expires_at=change_request.expires_at.isoformat(),
            )

            try:
                send_approval_expired_notification(locked_cr)
            except Exception as notification_error:
                logger.warning(
                    "expire_old_change_requests.notification_failed",
                    change_request_id=str(change_request.id),
                    error=str(notification_error),
                )

        except Exception as e:
            error_msg = f"Error expiring change request {change_request.id}: {str(e)}"
            errors.append(error_msg)
            logger.exception(
                "expire_old_change_requests.error",
                change_request_id=str(change_request.id),
                error=str(e),
            )

    result = {
        "expired_count": expired_count,
        "errors": errors,
    }

    logger.info("expire_old_change_requests.complete", **result)
    return result
