"""Resolves which provider, model and key an eval run should use.

A judge runs only on the provider key pinned in its `model_configuration`. `model_spec()` turns the
serialized config into a `ModelSpec` whose `resolve()` produces a concrete `ResolvedModel`, and a
judge with no configuration or no pinned key raises `provider_key_required`.

Lives in the temporal layer because `resolve()` raises Temporal `ApplicationError`s whose
`error_type` details the workflows pattern-match on (disable, key-state updates, emails).
"""

from dataclasses import dataclass
from typing import Any, Protocol

from django.utils import timezone

from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import retry_on_db_connection_drop

from products.ai_observability.backend.models.provider_keys import LLMProviderKey


@dataclass(frozen=True)
class ResolvedModel:
    provider: str
    model: str
    provider_key: LLMProviderKey | None

    @property
    def is_byok(self) -> bool:
        return self.provider_key is not None


class ModelSpec(Protocol):
    def resolve(self, team_id: int) -> ResolvedModel: ...


@dataclass(frozen=True)
class ExplicitModelSpec:
    """The eval's own provider, model and pinned key."""

    provider: str
    model: str
    provider_key_id: str | None

    def resolve(self, team_id: int) -> ResolvedModel:
        if not self.provider_key_id:
            raise _provider_key_required()
        return ResolvedModel(self.provider, self.model, _resolve_key_by_id(team_id, self.provider_key_id))


@dataclass(frozen=True)
class UnconfiguredModelSpec:
    """A judge with no model configuration has no key to run on."""

    def resolve(self, team_id: int) -> ResolvedModel:
        raise _provider_key_required()


def model_spec(model_configuration: dict[str, Any] | None) -> ModelSpec:
    if model_configuration:
        return ExplicitModelSpec(
            provider=model_configuration["provider"],
            model=model_configuration["model"],
            provider_key_id=model_configuration.get("provider_key_id"),
        )
    return UnconfiguredModelSpec()


def _provider_key_required() -> ApplicationError:
    return ApplicationError(
        "Add a provider API key to run this evaluation.",
        {"error_type": "provider_key_required"},
        non_retryable=True,
    )


def _resolve_key_by_id(team_id: int, key_id: str) -> LLMProviderKey:
    try:
        key = retry_on_db_connection_drop(lambda: LLMProviderKey.objects.get(id=key_id, team_id=team_id))
    except LLMProviderKey.DoesNotExist:
        raise ApplicationError(
            "Provider key not found.",
            {"error_type": "key_not_found", "key_id": key_id},
            non_retryable=True,
        )
    return _ensure_usable(key)


# A key that was never validated is not the same thing as one the provider rejected: the state
# decides whether the user should validate, re-validate, or replace it. Annotated as `dict[str, str]`
# because the enum members would otherwise infer `State` keys and the lookup on the stored string
# would not typecheck.
_UNUSABLE_KEY_MESSAGES: dict[str, str] = {
    LLMProviderKey.State.UNKNOWN: (
        "This API key has not been validated yet. Validate it in AI observability settings, "
        "then re-enable this evaluation."
    ),
    LLMProviderKey.State.INVALID: (
        "This API key was rejected by the provider. Re-validate it, or replace it, then re-enable this evaluation."
    ),
    LLMProviderKey.State.ERROR: (
        "This API key last failed with a provider error. Check its status in AI observability "
        "settings, then re-validate it."
    ),
}


def _ensure_usable(key: LLMProviderKey) -> LLMProviderKey:
    if key.state != LLMProviderKey.State.OK:
        # A state added later still has to produce a message rather than a KeyError.
        message = _UNUSABLE_KEY_MESSAGES.get(
            key.state,
            "This API key cannot be used. Re-validate it, or replace it, then re-enable this evaluation.",
        )
        raise ApplicationError(
            message,
            {"error_type": "key_invalid", "key_id": str(key.id), "key_state": key.state},
            non_retryable=True,
        )
    # Retrying this write is safe because the timestamp is fixed before it, so a second attempt
    # persists the same value rather than drifting it forward.
    key.last_used_at = timezone.now()
    retry_on_db_connection_drop(lambda: key.save(update_fields=["last_used_at"]))
    return key
