from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import UUIDTModel

from .provider_keys import llm_provider_choices


def provider_requires_key(provider: str) -> bool:
    """Whether this provider's models can only be listed with a BYOK key. PostHog funds no models
    for it, so a keyless lookup has nothing to return."""
    from products.ai_observability.backend.llm import (  # noqa: PLC0415 - keeps the provider SDKs off the import path
        PLAYGROUND_MODELS_BY_PROVIDER,
    )

    return provider not in PLAYGROUND_MODELS_BY_PROVIDER


class LLMModelConfiguration(UUIDTModel):
    """Configuration for LLM model selection, used by evals and other features."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    provider = models.CharField(max_length=50, choices=llm_provider_choices)
    model = models.CharField(max_length=100)
    provider_key = models.ForeignKey(
        "ai_observability.LLMProviderKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="model_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "llm_analytics_llmmodelconfiguration"
        indexes = [
            models.Index(fields=["team", "provider"]),
        ]

    def __str__(self) -> str:
        key_info = f" (key: {self.provider_key.name})" if self.provider_key else " (PostHog default)"
        return f"{self.provider}/{self.model}{key_info}"

    def clean(self) -> None:
        """Django validation - works for both persisted and in-memory instances."""
        super().clean()
        self._validate_provider_key_match()

    def _validate_provider_key_match(self) -> None:
        """If a key is set, provider must match the key's provider."""
        if self.provider_key and self.provider_key.provider != self.provider:
            raise ValidationError(
                {"provider": f"Provider '{self.provider}' does not match key provider '{self.provider_key.provider}'"}
            )

    def get_available_models(self) -> list[str]:
        """Get available models — delegates to the provider API if a BYOK key is
        present, otherwise returns the playground model list (PostHog pays)."""
        if self.provider_key:
            from products.ai_observability.backend.llm.client import Client

            api_key = self.provider_key.encrypted_config.get("api_key")
            return Client.list_models(self.provider, api_key)

        from products.ai_observability.backend.llm import PLAYGROUND_MODELS_BY_PROVIDER

        return PLAYGROUND_MODELS_BY_PROVIDER.get(self.provider, [])

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
