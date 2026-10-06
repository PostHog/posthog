"""Fireworks provider for unified LLM client.

Fireworks provides an OpenAI-compatible API and is BYOKEY-only.
"""

from products.ai_observability.backend.llm.providers.openai_compatible_byok import OpenAICompatibleByokAdapter

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"


class FireworksAdapter(OpenAICompatibleByokAdapter):
    """Fireworks provider that reuses OpenAI's completion/streaming logic."""

    name = "fireworks"
    BASE_URL = FIREWORKS_BASE_URL
    PROVIDER_DISPLAY_NAME = "Fireworks"
    # Fireworks returns 412 when it suspends an account for billing. Other OpenAI-compatible
    # providers can send 412 for unrelated reasons, so only this adapter treats it as exhausted quota.
    QUOTA_EXHAUSTED_STATUS_CODES = OpenAICompatibleByokAdapter.QUOTA_EXHAUSTED_STATUS_CODES | {412}
