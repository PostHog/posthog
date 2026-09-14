import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from products.ai_training.backend import config
from products.ai_training.backend.logic import consent


def privacy_enabled() -> bool:
    return config.privacy_enabled()


@contextmanager
def record_training_consent(organization_id: uuid.UUID, allowed: bool) -> Iterator[None]:
    with consent.record_training_consent(organization_id, allowed):
        yield


def queue_training_deletion(team_id: int, kind: str, identifiers: Sequence[str] = ()) -> None:
    consent.queue_training_deletion(team_id, kind, identifiers)
