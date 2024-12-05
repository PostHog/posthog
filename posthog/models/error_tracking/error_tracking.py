from django.db import models, transaction
from django.contrib.postgres.fields import ArrayField

from posthog.models.utils import UUIDModel
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.error_tracking.sql import INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT


class ErrorTrackingIssue(UUIDModel):
    class Status(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        PENDING_RELEASE = "pending_release", "Pending release"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.TextField(choices=Status.choices, default=Status.ACTIVE, null=False)
    name = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def merge(self, issue_ids: list[str]) -> None:
        override_inserts: list[tuple[str, int, str]] = []

        with transaction.atomic():
            for issue_id in issue_ids:
                fingerprints = resolve_fingerprints_for_issue(team_id=self.team.pk, issue_id=issue_id)

                for fingerprint in fingerprints:
                    override_inserts.append(
                        update_error_tracking_issue_fingerprint(
                            team_id=self.team.pk, issue_id=self.id, fingerprint=fingerprint
                        )
                    )

            ErrorTrackingIssue.objects.filter(team=self.team, id__in=issue_ids).delete()

        update_error_tracking_issue_fingerprint_overrides(team_id=self.team.pk, override_inserts=override_inserts)

    def split(self, fingerprints: list[str]) -> None:
        override_inserts: list[tuple[str, int, str]] = []

        with transaction.atomic():
            for fingerprint in fingerprints:
                new_issue = ErrorTrackingIssue.objects.create(team=self.team)
                override_inserts.append(
                    update_error_tracking_issue_fingerprint(
                        team_id=self.team.pk, issue_id=new_issue.id, fingerprint=fingerprint
                    )
                )

            update_error_tracking_issue_fingerprint_overrides(team_id=self.team.pk, override_inserts=override_inserts)


class ErrorTrackingIssueAssignment(UUIDModel):
    issue = models.ForeignKey(ErrorTrackingIssue, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["issue", "user"], name="unique_on_user_and_issue")]


class ErrorTrackingIssueFingerprintV2(UUIDModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    issue = models.ForeignKey(ErrorTrackingIssue, on_delete=models.CASCADE)
    fingerprint = models.TextField(null=False, blank=False)
    # current version of the id, used to sync with ClickHouse and collapse rows correctly for overrides ClickHouse table
    version = models.BigIntegerField(blank=True, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "fingerprint"], name="unique_fingerprint_for_team")]


class ErrorTrackingSymbolSet(UUIDModel):
    # Derived from the symbol set reference
    ref = models.TextField(null=False, blank=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    # How we stored this symbol set, and where to look for it
    # These are null if we failed to find a symbol set for a given reference. We store a
    # row anyway, so if someone comes along later and uploads a symbol set for this reference,
    # we can know which frame resolution results below to drop.
    storage_ptr = models.TextField(null=True, blank=False)

    # If we failed to resolve this symbol set, we store the reason here, so
    # we can return the language-relevant error in the future.
    failure_reason = models.TextField(null=True, blank=True)
    content_hash = models.TextField(null=True, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "ref"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "ref"], name="unique_ref_per_team"),
        ]


class ErrorTrackingStackFrame(UUIDModel):
    # Produced by a raw frame
    raw_id = models.TextField(null=False, blank=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    symbol_set = models.ForeignKey("ErrorTrackingSymbolSet", on_delete=models.CASCADE, null=True)
    contents = models.JSONField(null=False, blank=False)
    resolved = models.BooleanField(null=False, blank=False)
    # The context around the frame, +/- a few lines, if we can get it
    context = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "raw_id"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team_id", "raw_id"], name="unique_raw_id_per_team"),
        ]


# DEPRECATED: Use ErrorTrackingIssue instead
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


# DEPRECATED: Use ErrorTrackingIssueFingerprintV2 instead
class ErrorTrackingIssueFingerprint(models.Model):
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    issue = models.ForeignKey(ErrorTrackingGroup, on_delete=models.CASCADE)
    fingerprint = models.TextField(null=False, blank=False)
    # current version of the id, used to sync with ClickHouse and collapse rows correctly for overrides ClickHouse table
    version = models.BigIntegerField(blank=True, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "fingerprint"], name="unique fingerprint for team")]


def resolve_fingerprints_for_issue(team_id: int, issue_id: str) -> list[str]:
    override_records = ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id=issue_id)
    return [r.fingerprint for r in override_records]


def update_error_tracking_issue_fingerprint(team_id: int, issue_id: str, fingerprint: str) -> tuple[str, int, str]:
    issue_fingerprint = ErrorTrackingIssueFingerprintV2.objects.select_for_update().get(
        team_id=team_id, fingerprint=fingerprint
    )
    issue_fingerprint.issue_id = issue_id
    issue_fingerprint.version = (issue_fingerprint.version or 0) + 1
    issue_fingerprint.save(update_fields=["version", "issue_id"])

    return (fingerprint, issue_fingerprint.version, issue_id)


def update_error_tracking_issue_fingerprint_overrides(
    team_id: int, override_inserts: list[tuple[str, int, str]]
) -> None:
    for fingerprint, version, issue_id in override_inserts:
        override_error_tracking_issue_fingerprint(
            team_id=team_id, fingerprint=fingerprint, issue_id=issue_id, version=version
        )


def override_error_tracking_issue_fingerprint(
    team_id: int,
    fingerprint: str,
    issue_id: str,
    version=0,
    is_deleted: bool = False,
    sync: bool = False,
) -> None:
    p = ClickhouseProducer()
    p.produce(
        topic=KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
        sql=INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
        data={
            "team_id": team_id,
            "fingerprint": fingerprint,
            "issue_id": issue_id,
            "version": version,
            "is_deleted": int(is_deleted),
        },
        sync=sync,
    )
