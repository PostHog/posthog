from django.db import models


class ErrorTrackingGroup(models.Model):
    class Status(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        PENDING_RELEASE = "pending_release", "Pending release"

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    assignee: models.ForeignKey = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    status: models.CharField = models.CharField(max_length=40, choices=Status.choices, default=Status.ACTIVE)


class ErrorTrackingFingerprint(models.Model):
    group: ErrorTrackingGroup = models.ForeignKey("ErrorTrackingGroup", on_delete=models.CASCADE)
    value: models.CharField = models.CharField(max_length=200)
