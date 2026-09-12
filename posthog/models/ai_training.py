import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from posthog.models.scoping.manager import EnvironmentScopedManager


class AITrainingConsent(models.Model):
    organization_id = models.UUIDField(primary_key=True)
    allowed = models.BooleanField(default=False)
    granted_at_ms = models.BigIntegerField(default=0)
    changed_at_ms = models.BigIntegerField(default=0)
    revision = models.BigIntegerField(default=0)


class AITrainingPrivacyRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.UUIDField(null=True)
    team_id = models.BigIntegerField(null=True)
    kind = models.CharField(max_length=32)
    identifiers = models.JSONField(default=list)
    allowed = models.BooleanField(null=True)
    granted_at_ms = models.BigIntegerField(default=0)
    changed_at_ms = models.BigIntegerField(default=0)
    revision = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    leased_until = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True)
    cursor = models.JSONField(default=dict)

    all_teams = models.Manager()
    objects = EnvironmentScopedManager()

    class Meta:
        default_manager_name = "all_teams"
        indexes = [
            models.Index(
                fields=["created_at"],
                condition=models.Q(completed_at__isnull=True),
                name="ai_training_pending_requests",
            )
        ]


def privacy_enabled() -> bool:
    return bool(getattr(settings, "AI_RESEARCH_REPLAY_PRIVACY_TABLE", ""))


@contextmanager
def record_training_consent(organization_id: uuid.UUID, allowed: bool) -> Iterator[None]:
    if not privacy_enabled():
        yield
        return
    with transaction.atomic():
        state, created = AITrainingConsent.objects.get_or_create(organization_id=organization_id)
        state = AITrainingConsent.objects.select_for_update().get(organization_id=organization_id)
        yield
        if not created and state.revision > 0 and state.allowed == allowed:
            return
        changed_at = max(time.time_ns() // 1_000_000, state.changed_at_ms + 1)
        if allowed:
            state.granted_at_ms = changed_at
        state.allowed = allowed
        state.changed_at_ms = changed_at
        state.revision += 1
        state.save()
        AITrainingPrivacyRequest.objects.unscoped().create(
            organization_id=organization_id,
            kind="consent",
            allowed=allowed,
            granted_at_ms=state.granted_at_ms,
            changed_at_ms=changed_at,
            revision=state.revision,
        )


def queue_training_deletion(team_id: int, kind: str, identifiers: Sequence[str] = ()) -> None:
    if not privacy_enabled():
        return
    if kind not in {"team", "session", "distinct"}:
        raise ValueError("Unsupported AI training deletion scope")
    if kind == "session":
        normalized = []
        for value in identifiers:
            try:
                session_id = uuid.UUID(value)
            except (ValueError, AttributeError):
                continue
            if session_id.version == 7:
                normalized.append(str(session_id))
        identifiers = normalized
    unique = sorted(set(identifiers))
    if kind != "team" and not unique:
        return
    requests = [
        AITrainingPrivacyRequest(team_id=team_id, kind=kind, identifiers=unique[offset : offset + 1000])
        for offset in range(0, max(1, len(unique)), 1000)
    ]
    AITrainingPrivacyRequest.objects.for_team(team_id).bulk_create(requests)
