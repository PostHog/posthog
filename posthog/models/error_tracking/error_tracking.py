from django.db import models
from django.contrib.postgres.fields import ArrayField
from posthog.models.utils import UUIDModel
from django.db import transaction
from django.db.models import Q, QuerySet


class ErrorTrackingGroup(UUIDModel):
    class Status(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        PENDING_RELEASE = "pending_release", "Pending release"

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    fingerprint: models.TextField = models.TextField(null=False, blank=False)
    merged_fingerprints: ArrayField = ArrayField(models.TextField(null=False, blank=False), default=list)
    status: models.CharField = models.CharField(
        max_length=40, choices=Status.choices, default=Status.ACTIVE, null=False
    )
    assignee: models.ForeignKey = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    @classmethod
    def filter_fingerprints(cls, queryset, fingerprints: list[str]) -> QuerySet:
        query = Q(fingerprint__in=fingerprints)

        for fp in fingerprints:
            query |= Q(merged_fingerprints__contains=[fp])

        return queryset.filter(query)

    @transaction.atomic
    def merge(self, fingerprints: list[str]) -> None:
        if not fingerprints:
            return

        merged_fingerprints = set(self.merged_fingerprints)
        merged_fingerprints.update(fingerprints)

        merging_groups = ErrorTrackingGroup.objects.filter(team=self.team, fingerprint__in=fingerprints)
        for group in merging_groups:
            merged_fingerprints |= set(group.merged_fingerprints)

        merging_groups.delete()
        self.merged_fingerprints = list(merged_fingerprints)
        self.save()
