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

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    fingerprint: ArrayField = ArrayField(models.TextField(null=False, blank=False), null=False, blank=False)
    merged_fingerprints: ArrayField = ArrayField(
        ArrayField(models.TextField(null=False, blank=False), null=False, blank=False),
        null=False,
        blank=False,
        default=list,
    )
    status = models.CharField(max_length=40, choices=Status.choices, default=Status.ACTIVE, null=False)
    assignee = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    @classmethod
    def filter_fingerprints(cls, queryset, fingerprints: list[list]) -> QuerySet:
        query = Q(fingerprint__in=fingerprints)

        for fp in fingerprints:
            query |= Q(merged_fingerprints__contains=fp)

        return queryset.filter(query)

    @transaction.atomic
    def merge(self, fingerprints: list[list[str]]) -> None:
        if not fingerprints:
            return

        # sets don't like lists so we're converting fingerprints to tuples
        def convert_fingerprints_to_tuples(fps: list[list[str]]):
            return [tuple(f) for f in fps]

        merged_fingerprints = set(convert_fingerprints_to_tuples(self.merged_fingerprints))
        merged_fingerprints.update(convert_fingerprints_to_tuples(fingerprints))

        merging_groups = ErrorTrackingGroup.objects.filter(team=self.team, fingerprint__in=fingerprints)
        for group in merging_groups:
            merged_fingerprints |= set(convert_fingerprints_to_tuples(group.merged_fingerprints))

        merging_groups.delete()
        # converting back to list of lists before saving
        self.merged_fingerprints = [list(f) for f in merged_fingerprints]
        self.save()


class ErrorTrackingSymbolSet(UUIDModel):
    class StorageMethod(models.TextChoices):
        S3 = "s3", "s3"
        FILE = "file", "file"

    # Derived from the symbol set reference
    ref = models.TextField(null=False, blank=False)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    # How we stored this symbol set, and where to look for it
    # These are null if we failed to find a symbol set for a given reference. We store a
    # row anyway, so if someone comes along later and uploads a symbol set for this reference,
    # we can know which frame resolution results below to drop.
    storage_method = models.TextField(choices=StorageMethod.choices, default=StorageMethod.S3, null=True)
    storage_ptr = models.TextField(null=True, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "id"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "id"], name="unique_id_per_team"),
        ]


class ErrorTrackingStackFrame(UUIDModel):
    # Produced by a raw frame
    raw_id = models.TextField(null=False, blank=False)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    symbol_set = models.ForeignKey("ErrorTrackingSymbolSet", on_delete=models.CASCADE, null=True)
    contents = models.JSONField(null=False, blank=False)
    resolved = models.BooleanField(null=False, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "raw_id"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "raw_id"], name="unique_raw_id_per_team"),
        ]
