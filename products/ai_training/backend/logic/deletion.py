import uuid
from collections.abc import Sequence

from products.ai_training.backend.config import privacy_enabled
from products.ai_training.backend.models import AITrainingPrivacyRequest


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
