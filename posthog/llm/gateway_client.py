from collections.abc import Callable
from typing import Any, Literal

from django.conf import settings

import posthoganalytics
from openai import OpenAI

OpenAIModel = Literal[
    "gpt-5.2",
    "gpt-5-mini",
    "gpt-5-nano",
]
AnthropicModel = Literal[
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]
Model = OpenAIModel | AnthropicModel

ANTHROPIC_TO_OPENAI_FALLBACK: dict[str, str] = {
    "claude-opus-4-5": "gpt-5.2",
    "claude-sonnet-4-5": "gpt-5-mini",
    "claude-haiku-4-5": "gpt-5-nano",
}

VALID_PRODUCTS = frozenset({"llm_gateway", "array", "wizard", "django"})


class _ModelMappingProxy:
    """Proxy that intercepts method calls to map the model parameter."""

    def __init__(self, target: Any, model_mapper: Callable[[str], str]):
        self._target = target
        self._model_mapper = model_mapper

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        return _ModelMappingProxy(attr, self._model_mapper)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if "model" in kwargs:
            kwargs["model"] = self._model_mapper(kwargs["model"])
        return self._target(*args, **kwargs)


class LLMClient:
    """
    Wrapper around OpenAI client that handles model mapping for fallback scenarios.

    When the gateway is disabled and an Anthropic model is requested, the client
    automatically maps it to an equivalent OpenAI model.
    """

    def __init__(self, client: OpenAI, model_mapping: dict[str, str] | None = None):
        self._client = client
        self._model_mapping = model_mapping or {}

    def _map_model(self, model: str) -> str:
        return self._model_mapping.get(model, model)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        return _ModelMappingProxy(attr, self._map_model)


def get_llm_client(
    team_id: int | None = None,
    product: str = "django",
) -> LLMClient:
    """
    Get an LLM client that transparently handles model routing.

    When gateway is enabled: routes to gateway (supports all models)
    When gateway is disabled: uses direct OpenAI, mapping Anthropic → OpenAI

    Callers should ALWAYS pass the `user` parameter in their API calls
    to attribute usage to the actual end-user.
    """
    if product not in VALID_PRODUCTS:
        raise ValueError(f"Invalid product '{product}'. Must be one of: {sorted(VALID_PRODUCTS)}")

    use_gateway = posthoganalytics.feature_enabled(
        "use-llm-gateway",
        str(team_id) if team_id else "default",
        groups={"project": str(team_id)} if team_id else None,
        send_feature_flag_events=False,
    )

    if use_gateway and settings.LLM_GATEWAY_URL and settings.LLM_GATEWAY_API_KEY:
        base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/{product}/v1"
        client = OpenAI(base_url=base_url, api_key=settings.LLM_GATEWAY_API_KEY)
        return LLMClient(client)

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return LLMClient(client, model_mapping=ANTHROPIC_TO_OPENAI_FALLBACK)
