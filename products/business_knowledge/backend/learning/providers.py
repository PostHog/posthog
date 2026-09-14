from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import EvidenceBundle, EvidenceRef, validate_learning_provider_name

# Other products register here so Business knowledge never imports them.


class LearningEvidenceProvider(Protocol):
    name: str

    # Coordinator passes the environment the tickets live in, not the canonical parent.
    def collect(self, team_id: int, *, since: datetime, limit: int) -> list[EvidenceRef]: ...

    # Look up with ref.source_team_id. ticket_id alone is not tenant-scoped.
    def load(self, ref: EvidenceRef) -> EvidenceBundle | None: ...


_providers: dict[str, LearningEvidenceProvider] = {}


def register_learning_provider(provider: LearningEvidenceProvider) -> None:
    # Django can call AppConfig.ready() more than once, so callers must skip
    # when get_learning_provider(name) is already set.
    validate_learning_provider_name(provider.name)
    if provider.name in _providers:
        raise ValueError(f"learning provider {provider.name!r} is already registered")
    _providers[provider.name] = provider


def get_learning_provider(name: str) -> LearningEvidenceProvider | None:
    return _providers.get(name)


def get_learning_providers() -> list[LearningEvidenceProvider]:
    return list(_providers.values())
