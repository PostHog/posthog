import json
import hashlib
from typing import Any, Optional

from django.db import connection, models, transaction
from django.utils import timezone

import structlog

from posthog.models.utils import UUIDModel

logger = structlog.get_logger(__name__)


def _filter_existing_team_ids(team_ids: set[int]) -> set[int]:
    """Return the subset of team_ids that still exist in posthog_team.

    Health checks snapshot team IDs at workflow start and dispatch them to
    activities that may run minutes later — teams can be deleted in the
    meantime. Callers use this to drop orphaned team_ids before writes so a
    missing FK does not roll back the whole batch.
    """
    if not team_ids:
        return set()

    # Inline import — posthog.models.__init__ imports HealthIssue before Team,
    # so a module-level `from posthog.models.team import Team` here would
    # invert the load order and risk a partial-init failure.
    from posthog.models.team import Team

    existing = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    missing = team_ids - existing
    if missing:
        logger.warning(
            "health_issue_dropping_deleted_teams",
            dropped_count=len(missing),
            dropped_team_ids=sorted(missing),
        )
    return existing


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
        choices=Severity,
    )

    status = models.CharField(
        max_length=20,
        choices=Status,
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
    def upsert_issue(
        cls,
        team_id: int,
        kind: str,
        severity: str,
        payload: dict[str, Any],
        hash_keys: Optional[list[str]] = None,
    ) -> tuple["HealthIssue", bool]:
        unique_hash = cls.compute_unique_hash(kind, payload, hash_keys)

        issue, created = cls.objects.update_or_create(
            team_id=team_id,
            kind=kind,
            unique_hash=unique_hash,
            status=cls.Status.ACTIVE,
            defaults={
                "severity": severity,
                "payload": payload,
            },
        )

        return issue, created

    @classmethod
    def bulk_upsert(
        cls,
        kind: str,
        issues: list[dict[str, Any]],
    ) -> list["HealthIssue"]:
        """Upsert health issues; returns the rows that became active in this call.

        A row is "newly active" when it had no matching ACTIVE row before — this
        covers both brand-new issues and ones transitioning RESOLVED → ACTIVE
        (the partial unique constraint only covers ACTIVE rows, so a resolved
        row with the same hash does not block creation of a new active one).
        Rows that were already ACTIVE and just got their severity/payload
        refreshed are *not* returned — alert emission should fire on lifecycle
        transitions, not on every detection tick.
        """
        if not issues:
            return []

        now = timezone.now()

        incoming: dict[tuple[int, str], dict[str, Any]] = {}
        for issue in issues:
            key = (issue["team_id"], issue["unique_hash"])
            incoming[key] = issue

        # Serialize concurrent upserts for the same (kind, team_id) — SELECT
        # FOR UPDATE can't lock a row that doesn't exist yet, and READ
        # COMMITTED doesn't lock gaps, so two callers would otherwise both
        # decide a hash is new and race into a duplicate bulk_create. Locks
        # acquired in sorted order to avoid deadlocks across overlapping
        # team_id sets.
        kind_lock_key = int.from_bytes(hashlib.sha256(kind.encode()).digest()[:4], "big", signed=True)

        with transaction.atomic():
            # Teams can be deleted between the workflow's team-ID snapshot and
            # this upsert. A missing team would trigger a deferred FK violation
            # at COMMIT and roll back every row in the batch, not just the
            # orphan — so drop incoming rows for teams that no longer exist.
            #
            # Filter before acquiring advisory locks so we don't hold per-team
            # locks for IDs we're about to drop.
            team_ids = _filter_existing_team_ids({tid for tid, _ in incoming})
            if not team_ids:
                return []

            # Drop incoming rows for teams that no longer exist
            incoming = {key: value for key, value in incoming.items() if key[0] in team_ids}

            with connection.cursor() as cursor:
                for team_id in sorted(team_ids):
                    cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [kind_lock_key, team_id])

            existing_issues = {
                (issue.team_id, issue.unique_hash): issue
                for issue in cls.objects.filter(
                    kind=kind,
                    status=cls.Status.ACTIVE,
                    team_id__in=team_ids,
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
                HealthIssue.objects.bulk_create(to_create)

            if to_update:
                HealthIssue.objects.bulk_update(to_update, fields=["severity", "payload", "updated_at"])

        return to_create

    @classmethod
    def bulk_resolve(
        cls,
        kind: str,
        team_ids: set[int],
        keep_hashes: dict[int, set[str]] | None = None,
    ) -> list["HealthIssue"]:
        """Resolve stale active issues; returns the rows that transitioned ACTIVE -> RESOLVED.

        Each row is fetched before the update so callers can fire side effects
        (e.g. alert emission) on the exact set of transitioned rows. The
        in-memory copies are mutated to reflect post-update state.
        """
        if not team_ids:
            return []

        now = timezone.now()

        def _mark_resolved(rows: list[HealthIssue]) -> None:
            for row in rows:
                row.status = cls.Status.RESOLVED
                row.resolved_at = now
                row.updated_at = now

        resolved_rows: list[HealthIssue] = []

        with transaction.atomic():
            if not keep_hashes:
                qs = HealthIssue.objects.filter(
                    kind=kind,
                    status=cls.Status.ACTIVE,
                    team_id__in=team_ids,
                )
                resolved_rows = list(qs.select_for_update())
                qs.update(status=cls.Status.RESOLVED, resolved_at=now, updated_at=now)
                _mark_resolved(resolved_rows)
                return resolved_rows

            keep_hashes_by_team = {team_id: hashes for team_id, hashes in keep_hashes.items() if team_id in team_ids}
            team_ids_without_keep_hashes = team_ids - set(keep_hashes_by_team.keys())

            if team_ids_without_keep_hashes:
                qs = HealthIssue.objects.filter(
                    kind=kind,
                    status=cls.Status.ACTIVE,
                    team_id__in=team_ids_without_keep_hashes,
                )
                batch = list(qs.select_for_update())
                qs.update(status=cls.Status.RESOLVED, resolved_at=now, updated_at=now)
                resolved_rows.extend(batch)

            for team_id, hashes in keep_hashes_by_team.items():
                team_qs = HealthIssue.objects.filter(
                    kind=kind,
                    status=cls.Status.ACTIVE,
                    team_id=team_id,
                )
                if hashes:
                    team_qs = team_qs.exclude(unique_hash__in=hashes)
                batch = list(team_qs.select_for_update())
                team_qs.update(status=cls.Status.RESOLVED, resolved_at=now, updated_at=now)
                resolved_rows.extend(batch)

            _mark_resolved(resolved_rows)
            return resolved_rows

    def resolve(self) -> None:
        if self.status != self.Status.ACTIVE:
            raise ValueError(f"Cannot resolve a health issue with status '{self.status}'.")
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "updated_at"])
