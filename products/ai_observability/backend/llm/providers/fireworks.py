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
