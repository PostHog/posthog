import json
import hashlib
from typing import Any, Optional

from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class HealthIssue(UUIDModel):
    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        WARNING = "warning", "Warning"
        INFO = "info", "Info"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="health_issues",
    )

    type = models.CharField(max_length=100, db_index=True)

    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    payload = models.JSONField(default=dict)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    unique_hash = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                name="idx_health_team_type_active",
                fields=["team_id", "type"],
                condition=models.Q(status="active"),
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                name="unique_active_health_issue",
                fields=["team_id", "type", "unique_hash"],
                condition=models.Q(status="active"),
            ),
        ]

    def __str__(self) -> str:
        return f"HealthIssue: {self.team_id}, {self.type}, {self.severity}, {self.status}"

    @staticmethod
    def compute_unique_hash(type: str, payload: dict[str, Any], hash_keys: Optional[list[str]] = None) -> str:
        if hash_keys:
            hash_data = {k: payload.get(k) for k in hash_keys}
        else:
            hash_data = payload

        content = f"{type}:{json.dumps(hash_data, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()

    @classmethod
    def upsert_issue(
        cls,
        team_id: int,
        type: str,
        severity: str,
        payload: dict[str, Any],
        hash_keys: Optional[list[str]] = None,
    ) -> tuple["HealthIssue", bool]:
        unique_hash = cls.compute_unique_hash(type, payload, hash_keys)

        issue, created = cls.objects.update_or_create(
            team_id=team_id,
            type=type,
            unique_hash=unique_hash,
            status=cls.Status.ACTIVE,
            defaults={
                "severity": severity,
                "payload": payload,
            },
        )

        return issue, created

    def resolve(self) -> None:
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "updated_at"])

    def dismiss(self) -> None:
        self.status = self.Status.DISMISSED
        self.save(update_fields=["status", "updated_at"])

    def reactivate(self) -> None:
        self.status = self.Status.ACTIVE
        self.resolved_at = None
        self.save(update_fields=["status", "resolved_at", "updated_at"])
