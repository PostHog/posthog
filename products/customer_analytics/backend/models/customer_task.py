from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class CustomerTaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELED = "canceled", "Canceled"


class CustomerTaskActivityType(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    ARCHIVED = "archived", "Archived"
    RESTORED = "restored", "Restored"


class CustomerTask(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    account = models.ForeignKey(
        "customer_analytics.Account",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="customer_tasks",
        db_index=False,
    )
    name = models.CharField(max_length=400)
    description = models.TextField(null=True, blank=True)
    properties = models.JSONField(default=dict, db_default={})
    status = models.CharField(max_length=20, choices=CustomerTaskStatus.choices, default=CustomerTaskStatus.OPEN)
    assigned_to = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_customer_tasks",
        db_constraint=False,
        db_index=False,
    )
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_customer_tasks",
        db_constraint=False,
        db_index=False,
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_customer_tasks",
        db_constraint=False,
        db_index=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(status=CustomerTaskStatus.COMPLETED) & Q(completed_at__isnull=False))
                    | (~Q(status=CustomerTaskStatus.COMPLETED) & Q(completed_at__isnull=True))
                ),
                name="customer_task_completion_consistency",
            ),
        ]


class CustomerTaskActivity(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    task = models.ForeignKey(CustomerTask, on_delete=models.CASCADE, related_name="activities", db_index=False)
    actor = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_task_activities",
        db_constraint=False,
        db_index=False,
    )
    activity_type = models.CharField(max_length=20, choices=CustomerTaskActivityType.choices)
    changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
