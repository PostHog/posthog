from collections.abc import Sequence

from products.ai_training.backend import config
from products.ai_training.backend.logic import deletion


def privacy_enabled() -> bool:
    return config.privacy_enabled()


def queue_training_deletion(team_id: int, kind: str, identifiers: Sequence[str] = ()) -> None:
    deletion.queue_training_deletion(team_id, kind, identifiers)


def queue_person_training_deletion(team_id: int, distinct_ids: Sequence[str]) -> None:
    deletion.queue_person_training_deletion(team_id, distinct_ids)
