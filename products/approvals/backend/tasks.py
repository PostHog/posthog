from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit

from products.approvals.backend.experiment_policy_sync import sync_experiment_policies
from products.approvals.backend.models import ChangeRequest, ChangeRequestState, ValidationStatus
from products.approvals.backend.notifications import send_approval_expired_notification
from products.approvals.backend.services import requester_still_has_access

logger = get_logger(__name__)


# Pin the task name to its pre-move path so the beat schedule and any in-flight
# messages keep routing after the module moved out of posthog/approvals.
@shared_task(ignore_result=True, name="posthog.approvals.tasks.validate_pending_change_requests")
@skip_team_scope_audit
def validate_pending_change_requests() -> dict[str, Any]:
    """
    Periodic staleness check for pending change requests.

    Compares stored preconditions against the current resource state.
    Marks CRs as STALE when the underlying resource has been modified, which allows
    requesters to cancel even after approvals have been given. Re-checks CRs already
    marked STALE too, so one that matches its precondition again (e.g. after a
    transient lookup miss) returns to VALID instead of being latched permanently.
    """
    stale_count = 0
    healed_count = 0
    checked_count = 0
    errors: list[str] = []

    # Approved requests are revalidated too. The apply-time access check only runs once a request
    # is approved, so marking it invalid there and then never revisiting it would latch the mark
    # exactly where it is set. `expire_old_change_requests` already spans both states.
    pending_requests = ChangeRequest.objects.filter(
        state__in=[ChangeRequestState.PENDING, ChangeRequestState.APPROVED],
    )

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

            # Derive the status the request should hold, rather than branching per transition.
            # Branching missed the invalid-to-valid direction, which latched a request forever
            # once its requester lost access.
            if action_class.check_staleness(change_request.intent, context):
                status = ValidationStatus.STALE
                errors_for_status: Optional[dict[str, str]] = {
                    "staleness": "Resource has been modified since this change request was created"
                }
            elif not requester_still_has_access(change_request, context):
                status = ValidationStatus.INVALID
                errors_for_status = {
                    "access": "The requester no longer has edit access to this resource, or their account is gone."
                }
            else:
                status = ValidationStatus.VALID
                errors_for_status = None

            was = change_request.validation_status
            if status != was:
                change_request.validation_status = status
                change_request.validation_errors = errors_for_status
                change_request.validated_at = timezone.now()
                change_request.save(update_fields=["validation_status", "validation_errors", "validated_at"])
                if status == ValidationStatus.VALID:
                    healed_count += 1
                else:
                    stale_count += 1
                logger.info(
                    "validate_pending_change_requests.healed"
                    if status == ValidationStatus.VALID
                    else "validate_pending_change_requests.stale",
                    change_request_id=str(change_request.id),
                    status=status,
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
        "healed_count": healed_count,
        "errors": errors,
    }

    logger.info("validate_pending_change_requests.complete", **result)
    return result


@shared_task(ignore_result=True, name="posthog.approvals.tasks.expire_old_change_requests")
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


# TODO(experiment-approval-policies): temporary. See experiment_policy_sync.py for what to remove.
@shared_task(ignore_result=True)
@skip_team_scope_audit
def sync_experiment_approval_policies() -> None:
    sync_experiment_policies()
