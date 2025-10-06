import os
import json
import socket

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from celery import current_task

from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, ScheduledChange

models = {"FeatureFlag": FeatureFlag}

# Maximum number of retry attempts before marking as permanently failed
MAX_RETRY_ATTEMPTS = 5


def is_unrecoverable_error(exception: Exception) -> bool:
    """
    Determine if an exception represents an unrecoverable error that should not be retried.

    Unrecoverable errors include:
    - Validation errors (bad payload, invalid data)
    - Missing objects (feature flag doesn't exist)
    - Database constraint violations
    - Business logic errors

    Recoverable errors (should retry):
    - Database connection timeouts
    - Network connectivity issues
    - Temporary service unavailability
    """
    # Exception types that indicate permanent failures
    unrecoverable_types = (
        ValidationError,
        ObjectDoesNotExist,
        IntegrityError,
        ValueError,  # Bad payload structure
        KeyError,  # Missing required payload fields
        TypeError,  # Wrong data types in payload
    )

    # Check for specific error messages that indicate permanent failures
    error_message = str(exception).lower()
    permanent_error_indicators = [
        "invalid payload",
        "unrecognized operation",
        "does not exist",
        "constraint",
        "foreign key",
        "unique constraint",
    ]

    if any(indicator in error_message for indicator in permanent_error_indicators):
        return True

    return isinstance(exception, unrecoverable_types)


def process_scheduled_changes() -> None:
    try:
        with transaction.atomic():
            scheduled_changes = (
                ScheduledChange.objects.select_for_update(nowait=True)
                .filter(
                    executed_at__isnull=True,
                    scheduled_at__lte=timezone.now(),
                )
                .order_by("scheduled_at")[:10000]
            )

            for scheduled_change in scheduled_changes:
                try:
                    # Execute the change on the model instance
                    model = models[scheduled_change.model_name]
                    instance = model.objects.get(id=scheduled_change.record_id)
                    instance.scheduled_changes_dispatcher(
                        scheduled_change.payload, scheduled_change.created_by, scheduled_change_id=scheduled_change.id
                    )

                    # Mark scheduled change completed
                    scheduled_change.executed_at = timezone.now()
                    scheduled_change.save()

                except Exception as e:
                    # Build comprehensive failure context (only info not already in ScheduledChange columns)
                    failure_context: dict[str, str | int | bool] = {
                        "error": str(e),
                        "error_type": e.__class__.__name__,
                    }

                    # Add execution context
                    if current_task and hasattr(current_task, "request") and current_task.request:
                        task_id = getattr(current_task.request, "id", None)
                        worker_hostname = getattr(current_task.request, "hostname", None)
                        if task_id is not None:
                            failure_context["task_id"] = str(task_id)
                        if worker_hostname is not None:
                            failure_context["worker_hostname"] = str(worker_hostname)

                    # Add system context
                    try:
                        failure_context["hostname"] = os.getenv("HOSTNAME") or socket.gethostname()
                    except:
                        failure_context["hostname"] = "unknown"

                    # Increment failure count first
                    scheduled_change.failure_count += 1

                    # Determine if we will retry based on error type and failure count
                    is_unrecoverable = is_unrecoverable_error(e)
                    has_exceeded_max_retries = scheduled_change.failure_count >= MAX_RETRY_ATTEMPTS
                    will_retry = not is_unrecoverable and not has_exceeded_max_retries

                    # Add retry status to failure context
                    failure_context["will_retry"] = will_retry
                    failure_context["retry_count"] = scheduled_change.failure_count
                    failure_context["max_retries"] = MAX_RETRY_ATTEMPTS

                    if has_exceeded_max_retries:
                        failure_context["retry_exhausted"] = True

                    if is_unrecoverable:
                        failure_context["error_classification"] = "unrecoverable"
                    else:
                        failure_context["error_classification"] = "recoverable"

                    scheduled_change.failure_reason = json.dumps(failure_context)

                    # Only mark as permanently failed if we won't retry
                    if not will_retry:
                        scheduled_change.executed_at = timezone.now()
                    # For recoverable errors under retry limit, leave executed_at=NULL to allow retries

                    scheduled_change.save()
                    capture_exception(e)
    except OperationalError:
        # Failed to obtain the lock
        pass
