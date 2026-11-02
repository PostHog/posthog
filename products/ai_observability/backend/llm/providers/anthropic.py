"""Anthropic provider for unified LLM client."""

import uuid
import logging
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

import anthropic
import posthoganalytics
from anthropic.lib._parse._transform import transform_schema
from anthropic.types import MessageParam, TextBlockParam, ThinkingConfigEnabledParam
from posthoganalytics.ai.anthropic import Anthropic
from posthoganalytics.ai.anthropic.anthropic import WrappedMessages
from posthoganalytics.client import Client as PostHogClient
from pydantic import BaseModel

from products.ai_observability.backend.llm.attachments import AttachmentPart, convert_attachment_parts
from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ModelNotFoundError,
    ModelPermissionError,
    OutputTokenLimitError,
    ProviderConfigurationError,
    ProviderConnectionError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
    error_field_for_message,
    is_context_window_error_message,
    is_output_limit_error_message,
    stream_error_chunk,
)
from products.ai_observability.backend.llm.providers.azure_openai import is_allowed_azure_endpoint
from products.ai_observability.backend.llm.types import (
    AnalyticsContext,
    CompletionRequest,
    CompletionResponse,
    ReasoningLevel,
    StreamChunk,
    Usage,
)

logger = logging.getLogger(__name__)

# Shared by the adapter and the serializer so the error attributes to the endpoint field in the UI.
DISALLOWED_FOUNDRY_ENDPOINT_MESSAGE = (
    "Microsoft Foundry endpoint must be an https:// URL on an Azure domain (e.g. *.services.ai.azure.com)"
)

FOUNDRY_ENDPOINT_NOT_FOUND_MESSAGE = (
    "Microsoft Foundry endpoint not found. Check that the URL is the endpoint of your Foundry resource, "
    "for example https://my-resource.services.ai.azure.com/"
)

# Keep aligned with the `return` statements in `AnthropicAdapter._validate_foundry_key`.
_FOUNDRY_ERROR_FIELD_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("Microsoft Foundry endpoint must be", "azure_endpoint"),
    ("Microsoft Foundry endpoint not found", "azure_endpoint"),
    ("Could not connect to Microsoft Foundry", "azure_endpoint"),
    ("Invalid API key", "api_key"),
)

# Key validation is a single cheap call; don't inherit the long completion timeout.
FOUNDRY_VALIDATION_TIMEOUT = 10.0


def error_field_for_validation_message(error_message: str | None) -> str | None:
    """Map an Anthropic `validate_key` error message to the UI form field that should be highlighted."""
    return error_field_for_message(_FOUNDRY_ERROR_FIELD_BY_PREFIX, error_message)


def _names_a_missing_deployment(error: anthropic.APIStatusError) -> bool:
    """Return True when a Foundry 4xx is about the model or deployment, which means the key passed auth.

    Azure answers an unknown route with a generic 404 ("Resource not found") before it checks
    anything, so a 404 alone does not prove the endpoint or the key is right.
    """
    body = error.body if isinstance(error.body, dict) else {}
    nested = body.get("error")
    details = nested if isinstance(nested, dict) else body
    if details.get("code") == "DeploymentNotFound":
        return True
    message = str(details.get("message", "")).lower()
    return "deployment" in message or "model" in message


def foundry_base_url(azure_endpoint: str) -> str:
    """Build the Anthropic API base URL of a Microsoft Foundry resource.

    Foundry serves Claude under `/anthropic/` on the resource host. Users paste the resource
    endpoint, the `/anthropic/` URL, or a full `/anthropic/v1/messages` URL, so keep only the host.
    """
    if not is_allowed_azure_endpoint(azure_endpoint):
        raise ProviderConfigurationError(f"{DISALLOWED_FOUNDRY_ENDPOINT_MESSAGE}.")
    host = urlparse(azure_endpoint).hostname
    return f"https://{host}/anthropic/"


class _AnthropicFoundry(anthropic.AnthropicFoundry):
    """Foundry client that captures generations to PostHog, like the SDK's Bedrock and Vertex wrappers."""

    _ph_client: PostHogClient

    def __init__(self, posthog_client: PostHogClient, **kwargs: Any):
        super().__init__(**kwargs)
        self._ph_client = posthog_client
        self.messages = WrappedMessages(self)  # type: ignore[assignment]  # ty: ignore[invalid-assignment]


def _is_quota_or_billing_error(error: Exception) -> bool:
    error_message = str(error).lower()
    return any(token in error_message for token in ("quota", "credit", "billing"))


class AnthropicConfig:
    MAX_TOKENS: int = 8192
    MAX_THINKING_TOKENS: int = 4096
    # Thinking tokens count against max_tokens, so each level also raises max_tokens by its budget.
    REASONING_BUDGET_TOKENS: dict[ReasoningLevel, int] = {"minimal": 1024, "low": 2048, "medium": 4096, "high": 8192}
    # Models before Claude 4.6 take a fixed thinking budget. Newer models reject it and take an effort level.
    BUDGET_THINKING_MODEL_PREFIXES: tuple[str, ...] = (
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
        "claude-opus-4-1",
        "claude-opus-4-0",
        "claude-sonnet-4-0",
        # Dated IDs of Claude 4.0, such as claude-sonnet-4-20250514.
        "claude-opus-4-20",
        "claude-sonnet-4-20",
    )
    # Timeout in seconds for API calls. Set high to accommodate slow reasoning models.
    # Note: Infrastructure-level timeouts (load balancers, proxies) may still limit actual request duration.
    TIMEOUT: float = 300.0

    SUPPORTED_MODELS: list[str] = [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-1",
        "claude-opus-4-0",
        "claude-sonnet-4-0",
    ]

    # Models available in the PostHog-funded playground. Excludes expensive
    # opus tiers and includes one flagship sonnet for quality evaluation.
    PLAYGROUND_MODELS: list[str] = [
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]

    DEFAULT_MODEL: str = "claude-haiku-4-5"

    SUPPORTED_MODELS_WITH_CACHE_CONTROL: list[str] = [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-1",
        "claude-opus-4-0",
        "claude-sonnet-4-0",
    ]

    SUPPORTED_MODELS_WITH_THINKING: list[str] = [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-1",
        "claude-opus-4-0",
        "claude-sonnet-4-0",
    ]

    @staticmethod
    def supports_reasoning_level(model: str) -> bool:
        # Every Claude model after the 3 family can think, including ones newer than our model lists.
        return model.startswith("claude-") and not model.startswith("claude-3")


class AnthropicAdapter:
    """Anthropic provider implementing the unified Client interface."""

    name = "anthropic"

    def __init__(self, foundry_endpoint: str = ""):
        # Set when the key belongs to a Microsoft Foundry resource that serves Claude.
        self.foundry_endpoint = foundry_endpoint

    def _create_client(self, api_key: str, analytics: AnalyticsContext) -> Any:
        from products.ai_observability.backend.llm.providers._diagnostics import tagged_http_client

        posthog_client = posthoganalytics.default_client
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": AnthropicConfig.TIMEOUT,
            "http_client": tagged_http_client(timeout=AnthropicConfig.TIMEOUT),
        }
        if self.foundry_endpoint:
            kwargs["base_url"] = foundry_base_url(self.foundry_endpoint)
            if analytics.capture and posthog_client:
                return _AnthropicFoundry(posthog_client=posthog_client, **kwargs)
            return anthropic.AnthropicFoundry(**kwargs)
        if analytics.capture and posthog_client:
            return Anthropic(posthog_client=posthog_client, **kwargs)
        return anthropic.Anthropic(**kwargs)

    def complete(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        _base_url: str | None = None,
    ) -> CompletionResponse:
        """Non-streaming completion with optional structured output."""
        effective_api_key = api_key or self._get_default_api_key()
        client = self._create_client(effective_api_key, analytics)

        messages: Any = convert_attachment_parts(request.messages, _anthropic_attachment_block)
        system_prompt = request.system or ""
        use_structured = request.response_format and issubclass(request.response_format, BaseModel)

        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "system": system_prompt,
            "messages": messages,
            "max_tokens": request.max_tokens or AnthropicConfig.MAX_TOKENS,
            **(self._build_analytics_kwargs(analytics, client)),
        }

        # Anthropic deprecated the sampling params (temperature/top_p/top_k) on newer models and
        # recommends omitting them (https://platform.claude.com/docs/en/about-claude/model-deprecations).
        # Forward temperature only when a caller explicitly set one.
        if request.temperature is not None:
            create_kwargs["temperature"] = request.temperature

        if use_structured:
            assert request.response_format is not None
            json_schema = self._build_output_schema(request.response_format)
            create_kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": json_schema,
                }
            }

        if request.reasoning_level and AnthropicConfig.supports_reasoning_level(request.model):
            self._apply_reasoning_level(create_kwargs, request.model, request.reasoning_level)

        try:
            response = client.messages.create(**create_kwargs)

            usage = Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            )

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            parsed: BaseModel | None = None
            if use_structured:
                if response.stop_reason == "max_tokens":
                    raise OutputTokenLimitError("The model reached its output token limit.")
                assert request.response_format is not None
                try:
                    parsed = request.response_format.model_validate_json(content)
                except Exception as e:
                    raise StructuredOutputParseError(f"Failed to parse structured output: {e}") from e

            return CompletionResponse(
                content=content,
                model=request.model,
                usage=usage,
                parsed=parsed,
            )
        except Exception as e:
            mapped = self._mapped_error(e, request.model)
            if mapped is not None:
                raise mapped from e
            raise

    @staticmethod
    def _apply_reasoning_level(create_kwargs: dict[str, Any], model: str, level: ReasoningLevel) -> None:
        budget = AnthropicConfig.REASONING_BUDGET_TOKENS[level]
        create_kwargs["max_tokens"] += budget
        if model.startswith(AnthropicConfig.BUDGET_THINKING_MODEL_PREFIXES):
            create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            return
        create_kwargs["thinking"] = {"type": "adaptive"}
        # Claude has no "minimal" effort level.
        create_kwargs.setdefault("output_config", {})["effort"] = "low" if level == "minimal" else level

    def _mapped_error(self, error: Exception, model: str) -> LLMError | None:
        """Normalize a provider exception into the shared taxonomy, or None when it isn't ours.

        `complete` and `stream` both route through this, so the same provider failure reads the
        same way whether the caller streamed it or not.
        """
        if isinstance(error, anthropic.AuthenticationError):
            return AuthenticationError(str(error))
        if isinstance(error, anthropic.NotFoundError):
            # Anthropic answers a retired or misspelled model with a 404. Without this the
            # workflow burns its retries on an unmapped exception instead of telling the user
            # to pick another model.
            return ModelNotFoundError(model)
        if isinstance(error, anthropic.PermissionDeniedError):
            return ModelPermissionError(model)
        if isinstance(error, anthropic.BadRequestError):
            if _is_quota_or_billing_error(error):
                return QuotaExceededError(str(error))
            if is_context_window_error_message(str(error)):
                return ContextWindowExceededError(str(error))
            if is_output_limit_error_message(str(error)):
                return OutputTokenLimitError(str(error))
            return None
        if isinstance(error, anthropic.RateLimitError):
            if _is_quota_or_billing_error(error):
                return QuotaExceededError(str(error))
            return RateLimitError(str(error))
        if isinstance(error, anthropic.APIConnectionError):
            # Transient transport failure (connection reset, read timeout). Map to a quiet
            # retryable error so the caller retries silently instead of spamming error tracking.
            return ProviderConnectionError(str(error))
        return None

    def stream(
        self,
        request: CompletionRequest,
        api_key: str | None,
        analytics: AnalyticsContext,
        _base_url: str | None = None,
    ) -> Generator[StreamChunk]:
        """Streaming completion."""
        effective_api_key = api_key or self._get_default_api_key()
        model_id = request.model
        client = self._create_client(effective_api_key, analytics)

        reasoning_on = model_id in AnthropicConfig.SUPPORTED_MODELS_WITH_THINKING and request.thinking

        effective_max_tokens = request.max_tokens if request.max_tokens is not None else AnthropicConfig.MAX_TOKENS

        tools = self._convert_tools(request.tools) if request.tools else None

        system = request.system or ""
        messages = convert_attachment_parts(request.messages, _anthropic_attachment_block)

        # Handle cache control for supported models
        system_prompt: list[TextBlockParam] = []
        if model_id in AnthropicConfig.SUPPORTED_MODELS_WITH_CACHE_CONTROL:
            system_prompt = [TextBlockParam(**{"text": system, "type": "text", "cache_control": {"type": "ephemeral"}})]
            formatted_messages = self._prepare_messages_with_cache_control(messages)
        else:
            system_prompt = [TextBlockParam(text=system, type="text")]
            formatted_messages = [MessageParam(content=msg["content"], role=msg["role"]) for msg in messages]

        try:
            common_kwargs: dict = {
                "messages": formatted_messages,
                "max_tokens": effective_max_tokens,
                "model": model_id,
                "system": system_prompt,
                "stream": True,
            }

            # See complete(): forward temperature only when a caller explicitly set one.
            if request.temperature is not None:
                common_kwargs["temperature"] = request.temperature

            if analytics.capture:
                common_kwargs["posthog_distinct_id"] = analytics.distinct_id
                common_kwargs["posthog_trace_id"] = analytics.trace_id or str(uuid.uuid4())
                common_kwargs["posthog_properties"] = analytics.properties or {}
                common_kwargs["posthog_groups"] = analytics.groups or {}

            if tools is not None:
                common_kwargs["tools"] = tools

            if request.output_schema is not None:
                common_kwargs["output_config"] = {
                    "format": {"type": "json_schema", "schema": request.output_schema.schema}
                }

            if reasoning_on:
                stream = client.messages.create(
                    **common_kwargs,
                    thinking=ThinkingConfigEnabledParam(
                        type="enabled", budget_tokens=AnthropicConfig.MAX_THINKING_TOKENS
                    ),
                )
            else:
                stream = client.messages.create(**common_kwargs)

            # Inside the try: Anthropic reports an overload or a mid-request failure by raising
            # partway through iteration, which is the point where the user has nothing else to
            # read but this generator's chunks.
            for chunk in stream:
                if chunk.type == "message_start":
                    usage = chunk.message.usage
                    yield StreamChunk(
                        type="usage",
                        data={
                            "input_tokens": usage.input_tokens or 0,
                            "output_tokens": usage.output_tokens or 0,
                            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
                            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
                        },
                    )

                elif chunk.type == "message_delta":
                    yield StreamChunk(
                        type="usage",
                        data={"input_tokens": 0, "output_tokens": chunk.usage.output_tokens or 0},
                    )

                elif chunk.type == "content_block_start":
                    if chunk.content_block.type == "thinking":
                        yield StreamChunk(type="reasoning", data={"reasoning": chunk.content_block.thinking or ""})
                    elif chunk.content_block.type == "redacted_thinking":
                        yield StreamChunk(type="reasoning", data={"reasoning": "[Redacted thinking block]"})
                    elif chunk.content_block.type == "text":
                        if chunk.index > 0:
                            yield StreamChunk(type="text", data={"text": "\n"})
                        yield StreamChunk(type="text", data={"text": chunk.content_block.text})
                    elif chunk.content_block.type == "tool_use":
                        yield StreamChunk(
                            type="tool_call",
                            data={
                                "id": chunk.content_block.id,
                                "function": {
                                    "name": chunk.content_block.name,
                                    "arguments": "",
                                },
                            },
                        )

                elif chunk.type == "content_block_delta":
                    if chunk.delta.type == "thinking_delta":
                        yield StreamChunk(type="reasoning", data={"reasoning": chunk.delta.thinking})
                    elif chunk.delta.type == "text_delta":
                        yield StreamChunk(type="text", data={"text": chunk.delta.text})
                    elif chunk.delta.type == "input_json_delta":
                        yield StreamChunk(
                            type="tool_call",
                            data={
                                "id": None,
                                "function": {
                                    "name": "",
                                    "arguments": chunk.delta.partial_json,
                                },
                            },
                        )
        except Exception as e:
            yield stream_error_chunk(e, self._mapped_error(e, model_id), logger=logger, provider=self.name)

    @staticmethod
    def validate_key(api_key: str, **kwargs: Any) -> tuple[str, str | None]:
        """Validate an Anthropic API key by making a lightweight API call."""
        from products.ai_observability.backend.models.provider_keys import LLMProviderKey

        azure_endpoint = kwargs.get("azure_endpoint")
        if azure_endpoint:
            return AnthropicAdapter._validate_foundry_key(api_key, azure_endpoint)

        if not api_key.startswith("sk-ant-"):
            return (LLMProviderKey.State.INVALID, "Invalid key format (should start with 'sk-ant-')")
        try:
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return (LLMProviderKey.State.OK, None)
        except anthropic.AuthenticationError:
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except anthropic.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except anthropic.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Anthropic")
        except Exception as e:
            logger.exception(f"Anthropic key validation error: {e}")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def _validate_foundry_key(api_key: str, azure_endpoint: str) -> tuple[str, str | None]:
        """Validate a Microsoft Foundry key with a token count, which Foundry serves and does not bill.

        Foundry has no models endpoint, so the probe has to name a deployment. The default model ID
        is the default deployment name, but the user may have picked another name.
        """
        from products.ai_observability.backend.models.provider_keys import LLMProviderKey

        if not is_allowed_azure_endpoint(azure_endpoint):
            return (LLMProviderKey.State.INVALID, DISALLOWED_FOUNDRY_ENDPOINT_MESSAGE)
        try:
            client = anthropic.AnthropicFoundry(
                api_key=api_key,
                base_url=foundry_base_url(azure_endpoint),
                timeout=FOUNDRY_VALIDATION_TIMEOUT,
                max_retries=0,
            )
            client.messages.count_tokens(
                model=AnthropicConfig.DEFAULT_MODEL,
                messages=[{"role": "user", "content": "hi"}],
            )
            return (LLMProviderKey.State.OK, None)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            return (LLMProviderKey.State.INVALID, "Invalid API key")
        except anthropic.RateLimitError:
            return (LLMProviderKey.State.ERROR, "Rate limited, please try again later")
        except (anthropic.NotFoundError, anthropic.BadRequestError) as e:
            # The user picks the deployment later, in the model picker, so a missing default
            # deployment still counts as a working key.
            if _names_a_missing_deployment(e):
                return (LLMProviderKey.State.OK, None)
            if isinstance(e, anthropic.NotFoundError):
                return (LLMProviderKey.State.INVALID, FOUNDRY_ENDPOINT_NOT_FOUND_MESSAGE)
            logger.exception("Microsoft Foundry key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")
        except anthropic.APIConnectionError:
            return (LLMProviderKey.State.ERROR, "Could not connect to Microsoft Foundry endpoint")
        except Exception:
            logger.exception("Microsoft Foundry key validation error")
            return (LLMProviderKey.State.ERROR, "Validation failed, please try again")

    @staticmethod
    def recommended_models() -> set[str]:
        return set(AnthropicConfig.SUPPORTED_MODELS)

    @staticmethod
    def list_models(api_key: str | None = None, **kwargs: Any) -> list[str]:
        """List available Anthropic models.

        Without a key, returns the curated SUPPORTED_MODELS list.
        With a key, returns SUPPORTED_MODELS first, then remaining Claude models
        from the API sorted by creation date (newest first).
        With a Microsoft Foundry endpoint, returns SUPPORTED_MODELS: Foundry has no models
        endpoint, and a new deployment takes the model ID as its default name.
        """
        if not api_key or kwargs.get("azure_endpoint"):
            return AnthropicConfig.SUPPORTED_MODELS

        supported = set(AnthropicConfig.SUPPORTED_MODELS)
        try:
            client = anthropic.Anthropic(api_key=api_key, timeout=AnthropicConfig.TIMEOUT)
            api_models = client.models.list(limit=1000)
            filtered = [m for m in api_models.data if m.id not in supported and m.id.startswith("claude-")]
            filtered.sort(key=lambda m: m.created_at, reverse=True)
            other = [m.id for m in filtered]
            return list(AnthropicConfig.SUPPORTED_MODELS) + other
        except Exception:
            logger.exception("Error fetching Anthropic models from API")
            return AnthropicConfig.SUPPORTED_MODELS

    @staticmethod
    def get_api_key() -> str:
        """Get the default API key from settings."""
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in environment or settings")
        return api_key

    def _get_default_api_key(self) -> str:
        return self.get_api_key()

    @staticmethod
    def _build_output_schema(response_format: type[BaseModel]) -> dict[str, Any]:
        return transform_schema(response_format)

    def _build_analytics_kwargs(self, analytics: AnalyticsContext, client) -> dict:
        """Build PostHog analytics kwargs if using instrumented client."""
        if analytics.capture and isinstance(client, Anthropic | _AnthropicFoundry):
            return {
                "posthog_distinct_id": analytics.distinct_id,
                "posthog_trace_id": analytics.trace_id or str(uuid.uuid4()),
                "posthog_properties": analytics.properties or {},
                "posthog_groups": analytics.groups or {},
                "posthog_privacy_mode": analytics.privacy_mode,
            }
        return {}

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tools to Anthropic format if needed."""
        from products.ai_observability.backend.providers.formatters.tools_handler import LLMToolsHandler, ToolFormat

        handler = LLMToolsHandler(tools)
        result = handler.convert_to(ToolFormat.ANTHROPIC)
        assert result is not None, "tools must be non-empty when calling _convert_tools"
        return result

    def _prepare_messages_with_cache_control(self, messages: list[dict[str, Any]]) -> list[MessageParam]:
        """Prepare messages with cache control for supported models."""
        user_msg_indices = [i for i, msg in enumerate(messages) if msg["role"] == "user"]
        last_user_msg_index = user_msg_indices[-1] if user_msg_indices else -1
        second_last_msg_user_index = user_msg_indices[-2] if len(user_msg_indices) > 1 else -1

        prepared_messages: list[MessageParam] = []
        for index, message in enumerate(messages):
            if index in [last_user_msg_index, second_last_msg_user_index]:
                if isinstance(message["content"], str):
                    prepared_message = MessageParam(
                        content=[{"type": "text", "text": message["content"], "cache_control": {"type": "ephemeral"}}],
                        role=message["role"],
                    )
                else:
                    content_blocks = []
                    content = list(message["content"])
                    for i, content_block in enumerate(content):
                        if i == len(content) - 1:
                            content_blocks.append(
                                {
                                    **dict(content_block),
                                    "cache_control": {"type": "ephemeral"},
                                }
                            )
                        else:
                            content_blocks.append(dict(content_block))
                    prepared_message = MessageParam(content=content_blocks, role=message["role"])  # type: ignore
            else:
                prepared_message = MessageParam(content=message["content"], role=message["role"])
            prepared_messages.append(prepared_message)

        return prepared_messages


def _anthropic_attachment_block(part: AttachmentPart) -> dict[str, Any]:
    block_type = "document" if part.is_pdf else "image"
    if part.url is not None:
        return {"type": block_type, "source": {"type": "url", "url": part.url}}
    return {"type": block_type, "source": {"type": "base64", "media_type": part.mime_type, "data": part.base64()}}
