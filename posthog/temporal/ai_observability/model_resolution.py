"""Resolves which provider, model and key an eval or tagger run should use.

`model_configuration` is optional on both `Evaluation` and `Tagger`. A null value is not
"unconfigured" — it means "defer to the team's active key". `model_spec()` turns the (possibly
null) serialized config into a `ModelSpec` whose `resolve()` produces a concrete `ResolvedModel`,
so judge and tagger share one definition of what null means instead of each re-deriving it.

Evaluations and taggers require the team's own provider key: a keyless resolution (no pinned key
and no team active key) raises `provider_key_required`.

Lives in the temporal layer because `resolve()` raises Temporal `ApplicationError`s whose
`error_type` details the workflows pattern-match on (disable, key-state updates, emails).
"""

from dataclasses import dataclass
from typing import Any, Protocol

from django.utils import timezone

from temporalio.exceptions import ApplicationError

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
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
    """The eval/tagger pinned its own provider and model. Trust the stored pairing."""

    provider: str
    model: str
    provider_key_id: str | None

    def resolve(self, team_id: int) -> ResolvedModel:
        if self.provider_key_id:
            return ResolvedModel(self.provider, self.model, _resolve_key_by_id(team_id, self.provider_key_id))

        fallback = active_key_fallback(_eval_config(team_id), self.provider)
        if fallback is None:
            raise _provider_key_required()
        return ResolvedModel(self.provider, self.model, _ensure_usable(fallback))


@dataclass(frozen=True)
class DefaultModelSpec:
    """Null config: defer to the team's active BYOK key."""

    def resolve(self, team_id: int) -> ResolvedModel:
        key = _eval_config(team_id).active_provider_key
        if key is None:
            raise _provider_key_required()

        model = DEFAULT_MODEL_BY_PROVIDER.get(key.provider)
        if model is None:
            raise ApplicationError(
                f"No default model is available for provider '{key.provider}'. Set a model on the evaluation.",
                {"error_type": "no_default_model", "provider": key.provider},
                non_retryable=True,
            )
        return ResolvedModel(key.provider, model, _ensure_usable(key))


def model_spec(model_configuration: dict[str, Any] | None) -> ModelSpec:
    if model_configuration:
        return ExplicitModelSpec(
            provider=model_configuration["provider"],
            model=model_configuration["model"],
            provider_key_id=model_configuration.get("provider_key_id"),
        )
    return DefaultModelSpec()


def active_key_fallback(config: EvaluationConfig, provider: str) -> LLMProviderKey | None:
    """The BYOK key a config with no pinned key resolves to, or None when there is no usable active key."""
    key = config.active_provider_key
    return key if key is not None and key.provider == provider else None


def _eval_config(team_id: int) -> EvaluationConfig:
    config, _ = EvaluationConfig.objects.get_or_create(team_id=team_id)
    return config


def _provider_key_required() -> ApplicationError:
    return ApplicationError(
        "Add a provider API key to run this evaluation.",
        {"error_type": "provider_key_required"},
        non_retryable=True,
    )


def _resolve_key_by_id(team_id: int, key_id: str) -> LLMProviderKey:
    try:
        key = LLMProviderKey.objects.get(id=key_id, team_id=team_id)
    except LLMProviderKey.DoesNotExist:
        raise ApplicationError(
            "Provider key not found.",
            {"error_type": "key_not_found", "key_id": key_id},
            non_retryable=True,
        )
    return _ensure_usable(key)


def _ensure_usable(key: LLMProviderKey) -> LLMProviderKey:
    if key.state != LLMProviderKey.State.OK:
        raise ApplicationError(
            f"This API key has been disabled (status: {key.state}). Re-validate to recover, or replace it.",
            {"error_type": "key_invalid", "key_id": str(key.id), "key_state": key.state},
            non_retryable=True,
        )
    key.last_used_at = timezone.now()
    key.save(update_fields=["last_used_at"])
    return key
