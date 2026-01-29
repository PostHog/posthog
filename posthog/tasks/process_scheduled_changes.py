import os
import json
import socket
from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

import structlog
from celery import current_task
from dateutil.relativedelta import relativedelta
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, ScheduledChange

logger = structlog.get_logger(__name__)

models = {"FeatureFlag": FeatureFlag}

# Maximum number of retry attempts before marking as permanently failed
MAX_RETRY_ATTEMPTS = 5

# Prometheus metric for tracking missed scheduled executions
SCHEDULED_CHANGE_MISSED_EXECUTIONS = Counter(
    "posthog_scheduled_change_missed_executions_total",
    "Number of scheduled change executions that were skipped due to delayed processing",
    ["interval"],
)


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


def compute_next_run(current: datetime, interval: str) -> datetime:
    """
    Compute the next scheduled run time based on recurrence interval.

    Uses relativedelta for reliable date arithmetic:
    - Daily: adds exactly 1 day
    - Weekly: adds exactly 7 days
    - Monthly: adds 1 month, handling month-end edge cases
      (e.g., Jan 31 + 1 month = Feb 28/29, not Mar 3)
    - Yearly: adds 1 year, handling leap year edge cases
      (e.g., Feb 29 + 1 year = Feb 28 in non-leap years)

    Args:
        current: The current scheduled_at datetime
        interval: One of 'daily', 'weekly', 'monthly', 'yearly' (validated at API layer via
            ScheduledChange.RecurrenceInterval). We use str instead of Literal here
            because Django's TextChoices fields return str at runtime, not the enum type.

    Returns:
        The next scheduled datetime

    Raises:
        ValueError: If interval is not a recognized value
    """
    if interval == "daily":
        return current + relativedelta(days=1)
    elif interval == "weekly":
        return current + relativedelta(weeks=1)
    elif interval == "monthly":
        return current + relativedelta(months=1)
    elif interval == "yearly":
        return current + relativedelta(years=1)
    raise ValueError(f"Unknown recurrence interval: {interval}")


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
                # Skip paused recurring schedules (is_recurring=false but has recurrence_interval)
                # These are "paused" and should not execute until resumed
                is_paused = not scheduled_change.is_recurring and scheduled_change.recurrence_interval
                if is_paused:
                    continue

                try:
                    # Execute the change on the model instance
                    model = models[scheduled_change.model_name]
                    instance = model.objects.get(id=scheduled_change.record_id)
                    instance.scheduled_changes_dispatcher(
                        scheduled_change.payload, scheduled_change.created_by, scheduled_change_id=scheduled_change.id
                    )

                    # Handle recurring vs one-time schedules
                    if scheduled_change.is_recurring and scheduled_change.recurrence_interval:
                        # Compute next run time, handling delayed execution
                        next_run = compute_next_run(
                            scheduled_change.scheduled_at,
                            scheduled_change.recurrence_interval,
                        )
                        # If task execution was delayed and next_run is still in the past, skip ahead
                        # to avoid immediate re-trigger or missed executions piling up
                        now = timezone.now()
                        skipped_count = 0
                        while next_run <= now:
                            next_run = compute_next_run(next_run, scheduled_change.recurrence_interval)
                            skipped_count += 1

                        # Log and track if we skipped executions due to delayed processing
                        # (skipped_count > 1 means we skipped more than just advancing to the next run)
                        if skipped_count > 1:
                            missed_count = skipped_count - 1
                            logger.warning(
                                "Recurring schedule skipped executions due to delayed processing",
                                scheduled_change_id=scheduled_change.id,
                                missed_count=missed_count,
                                interval=scheduled_change.recurrence_interval,
                                next_run=next_run.isoformat(),
                            )
                            SCHEDULED_CHANGE_MISSED_EXECUTIONS.labels(
                                interval=scheduled_change.recurrence_interval
                            ).inc(missed_count)

                        # Check if end_date has passed - if so, mark as completed
                        if scheduled_change.end_date and next_run > scheduled_change.end_date:
                            scheduled_change.executed_at = now
                            scheduled_change.last_executed_at = now
                            scheduled_change.save()
                        else:
                            scheduled_change.scheduled_at = next_run
                            scheduled_change.last_executed_at = now
                            scheduled_change.save()
                    else:
                        # One-time schedule: mark as completed
                        # Note: We intentionally don't set last_executed_at for one-time schedules
                        # because executed_at already serves as the completion timestamp. last_executed_at
                        # is an audit field for recurring schedules to track "when did the last recurrence run"
                        # while executed_at=NULL (schedule still active).
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
