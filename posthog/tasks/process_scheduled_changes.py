from posthog.models import ScheduledChange
from django.utils import timezone
from posthog.models import FeatureFlag
from django.db import transaction, OperationalError

models = {"FeatureFlag": FeatureFlag}


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
                    instance.scheduled_changes_dispatcher(scheduled_change.payload)

                    # Mark scheduled change completed
                    scheduled_change.executed_at = timezone.now()
                    scheduled_change.save()

                except Exception as e:
                    # Store the failure reason
                    scheduled_change.failure_reason = str(e)
                    scheduled_change.executed_at = timezone.now()
                    scheduled_change.save()
    except OperationalError:
        # Failed to obtain the lock
        pass
