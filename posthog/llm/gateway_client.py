from typing import Literal

from django.conf import settings

from openai import OpenAI

Product = Literal[
    "llm_gateway", "array", "wizard", "django", "growth"
]  # If you add a product here, make sure it's also in llm_gateway/products/config.py


def get_llm_client(product: Product = "django") -> OpenAI:
    """
    Get an OpenAI-compatible client for the LLM gateway.

    The gateway supports all OpenAI and Anthropic models through a unified interface.
    Callers should ALWAYS pass the `user` parameter in API calls for attribution.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    return OpenAI(base_url=base_url, api_key=settings.LLM_GATEWAY_API_KEY)
