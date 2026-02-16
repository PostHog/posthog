import json
import hashlib
from typing import Any, Optional

from django.db import models
from django.db.models import Q
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

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="health_issues",
    )

    kind = models.CharField(max_length=100)

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

    dismissed = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    unique_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="unique_active_health_issue",
                fields=["team_id", "kind", "unique_hash"],
                condition=models.Q(status="active"),
            ),
        ]

    def __str__(self) -> str:
        return f"HealthIssue: {self.team_id}, {self.kind}, {self.severity}, {self.status}"

    @staticmethod
    def compute_unique_hash(kind: str, payload: dict[str, Any], hash_keys: Optional[list[str]] = None) -> str:
        if hash_keys is not None:
            hash_data = {k: payload.get(k) for k in sorted(hash_keys)}
        else:
            hash_data = payload

        content = f"{kind}:{json.dumps(hash_data, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()

    @classmethod
    def bulk_upsert(
        cls,
        kind: str,
        issues: list[dict[str, Any]],
    ) -> int:
        if not issues:
            return 0

        now = timezone.now()

        incoming: dict[tuple[int, str], dict[str, Any]] = {}
        for issue in issues:
            key = (issue["team_id"], issue["unique_hash"])
            incoming[key] = issue

        existing_issues = {
            (issue.team_id, issue.unique_hash): issue
            for issue in cls.objects.filter(
                kind=kind,
                status=cls.Status.ACTIVE,
                team_id__in={tid for tid, _ in incoming},
                unique_hash__in={h for _, h in incoming},
            )
        }

        to_create: list[HealthIssue] = []
        to_update: list[HealthIssue] = []

        for (team_id, unique_hash), data in incoming.items():
            existing = existing_issues.get((team_id, unique_hash))
            if existing is not None:
                existing.severity = data["severity"]
                existing.payload = data["payload"]
                existing.updated_at = now
                to_update.append(existing)
            else:
                to_create.append(
                    cls(
                        team_id=team_id,
                        kind=kind,
                        severity=data["severity"],
                        payload=data["payload"],
                        unique_hash=unique_hash,
                        status=cls.Status.ACTIVE,
                        created_at=now,
                        updated_at=now,
                    )
                )

        if to_create:
            cls.objects.bulk_create(to_create)

        if to_update:
            cls.objects.bulk_update(to_update, fields=["severity", "payload", "updated_at"])

        return len(to_create) + len(to_update)

    @classmethod
    def bulk_resolve(
        cls,
        kind: str,
        team_ids: set[int],
        keep_hashes: dict[int, set[str]] | None = None,
    ) -> int:
        if not team_ids:
            return 0

        now = timezone.now()

        qs = cls.objects.filter(
            kind=kind,
            status=cls.Status.ACTIVE,
            team_id__in=team_ids,
        )

        if keep_hashes:
            keep_q = Q()
            for team_id, hashes in keep_hashes.items():
                keep_q |= Q(team_id=team_id, unique_hash__in=hashes)
            qs = qs.exclude(keep_q)

        return qs.update(status=cls.Status.RESOLVED, resolved_at=now, updated_at=now)

    def resolve(self) -> None:
        if self.status != self.Status.ACTIVE:
            raise ValueError(f"Cannot resolve a health issue with status '{self.status}'.")
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "updated_at"])
