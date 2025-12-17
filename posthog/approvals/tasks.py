from typing import Any

from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.approvals.models import ChangeRequest, ChangeRequestState, ValidationStatus
from posthog.approvals.notifications import send_approval_expired_notification

logger = get_logger(__name__)


@shared_task(ignore_result=True)
def validate_pending_change_requests() -> dict[str, Any]:
    """
    Checks if:
    1. The underlying data has changed (staleness)
    2. The validation is still valid (re-run validation)
    """

    validated_count = 0
    invalidated_count = 0
    errors: list[str] = []

    pending_requests = ChangeRequest.objects.filter(state=ChangeRequestState.PENDING)

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

            # Build context for validation
            base_context = {
                "team": change_request.team,
                "team_id": change_request.team_id,
                "organization": change_request.organization,
            }
            context = action_class.prepare_context(change_request, base_context)

            is_valid, validation_errors = action_class.validate_intent(change_request.intent, context)

            if is_valid:
                change_request.validation_status = ValidationStatus.VALID
                change_request.validation_errors = None
                validated_count += 1
            else:
                change_request.validation_status = ValidationStatus.INVALID
                change_request.validation_errors = validation_errors
                invalidated_count += 1
                logger.info(
                    "validate_pending_change_requests.invalidated",
                    change_request_id=str(change_request.id),
                    errors=validation_errors,
                )

            change_request.validated_at = timezone.now()
            change_request.save(update_fields=["validation_status", "validation_errors", "validated_at"])

        except Exception as e:
            error_msg = f"Error validating change request {change_request.id}: {str(e)}"
            errors.append(error_msg)
            logger.exception(
                "validate_pending_change_requests.error",
                change_request_id=str(change_request.id),
                error=str(e),
            )

    result = {
        "validated_count": validated_count,
        "invalidated_count": invalidated_count,
        "errors": errors,
    }

    logger.info("validate_pending_change_requests.complete", **result)
    return result


@shared_task(ignore_result=True)
def expire_old_change_requests() -> dict[str, Any]:
    """
    Scheduled task to expire old pending change requests.

    Runs hourly via Celery beat.
    """
    now = timezone.now()
    expired_count = 0
    errors: list[str] = []

    pending_requests = ChangeRequest.objects.filter(
        state=ChangeRequestState.PENDING,
        expires_at__lte=now,
    )

    for change_request in pending_requests:
        try:
            change_request.state = ChangeRequestState.EXPIRED
            change_request.save(update_fields=["state"])
            expired_count += 1

            logger.info(
                "expire_old_change_requests.expired",
                change_request_id=str(change_request.id),
                action_key=change_request.action_key,
                expires_at=change_request.expires_at.isoformat(),
            )

            try:
                send_approval_expired_notification(change_request)
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
