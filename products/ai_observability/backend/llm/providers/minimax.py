"""MiniMax provider for unified LLM client.

MiniMax exposes an OpenAI-compatible API and is BYOKEY-only.
"""

from products.ai_observability.backend.llm.providers.openai_compatible_byok import OpenAICompatibleByokAdapter

MINIMAX_BASE_URL = "https://api.minimax.io/v1"


class MiniMaxAdapter(OpenAICompatibleByokAdapter):
    """MiniMax provider that reuses OpenAI's completion/streaming logic."""

    name = "minimax"
    BASE_URL = MINIMAX_BASE_URL
    PROVIDER_DISPLAY_NAME = "MiniMax"
