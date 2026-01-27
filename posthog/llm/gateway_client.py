from typing import Literal

from django.conf import settings

from openai import OpenAI

Product = Literal[
    "llm_gateway", "twig", "wizard", "django", "growth"
]  # If you add a product here, make sure it's also in services/llm-gateway/src/llm_gateway/products/config.py


def get_llm_client(product: Product = "django") -> OpenAI:
    """
    Get an OpenAI-compatible client for the LLM gateway.

    The gateway supports all OpenAI, Anthropic and Gemini chat models through a unified interface.

    If you want the user to be tracked by LLM A and rate limited correctly, you should supply the distinct_id as a `user` argument when making the LLM call. For example:

    client = get_llm_client()
    response = client.chat.completions.create(
        model="claude-opus-4-5",  # or any supported OpenAI, Anthropic or Gemini model
        messages=[...],
        user=request.user.distinct_id,  # user for analytics and rate limiting
    )

    Args:
        product: The product to use when making requests to the LLM gateway, should be one of the defined products in the gateway. You can use this to filter traces by the `ai_product` propertly, and also to define custom rate limits / model restrictions in the gateway. If not passed, it will default to the "django" product.
    """
    if not settings.LLM_GATEWAY_URL or not settings.LLM_GATEWAY_API_KEY:
        raise ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

    base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
    return OpenAI(base_url=base_url, api_key=settings.LLM_GATEWAY_API_KEY)
