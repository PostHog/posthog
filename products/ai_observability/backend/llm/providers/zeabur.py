"""Zeabur AI Hub provider for unified LLM client.

Zeabur AI Hub exposes an OpenAI-compatible API and is BYOKEY-only.
"""

from products.ai_observability.backend.llm.providers.openai_compatible_byok import OpenAICompatibleByokAdapter

# AI Hub is served from regional endpoints (sfo1, hnd1). Requests originate from
# PostHog's servers, so the US endpoint is used.
ZEABUR_BASE_URL = "https://sfo1.aihub.zeabur.ai/v1"


class ZeaburAdapter(OpenAICompatibleByokAdapter):
    """Zeabur AI Hub provider that reuses OpenAI's completion/streaming logic."""

    name = "zeabur"
    BASE_URL = ZEABUR_BASE_URL
    PROVIDER_DISPLAY_NAME = "Zeabur AI Hub"
