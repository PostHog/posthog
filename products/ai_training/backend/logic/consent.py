import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from django.db import transaction

from products.ai_training.backend.config import privacy_enabled
from products.ai_training.backend.models import AITrainingConsent, AITrainingPrivacyRequest


@contextmanager
def record_training_consent(organization_id: uuid.UUID, allowed: bool) -> Iterator[None]:
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
