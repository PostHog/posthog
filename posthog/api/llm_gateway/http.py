import json
import asyncio
import logging
from collections.abc import AsyncGenerator

from django.conf import settings
from django.http import StreamingHttpResponse

import litellm
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission
from posthog.rate_limit import LLMGatewayBurstRateThrottle, LLMGatewaySustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer

from ee.hogai.utils.aio import async_to_sync

from .serializers import (
    AnthropicMessagesRequestSerializer,
    AnthropicMessagesResponseSerializer,
    ChatCompletionRequestSerializer,
    ChatCompletionResponseSerializer,
    ErrorResponseSerializer,
)

logger = logging.getLogger(__name__)


class LLMGatewayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    def get_throttles(self):
        return [LLMGatewayBurstRateThrottle(), LLMGatewaySustainedRateThrottle()]

    async def _anthropic_stream(self, data: dict) -> AsyncGenerator[bytes, None]:
        response = await litellm.anthropic_messages(**data)
        async for chunk in response:
            yield chunk

    async def _openai_stream(self, data: dict) -> AsyncGenerator[bytes, None]:
        response = await litellm.acompletion(**data)
        async for chunk in response:
            yield chunk

    async def _format_as_sse(self, llm_stream: AsyncGenerator, request: Request) -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in llm_stream:
                if not request.META.get("SERVER_NAME"):
                    return
                chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                yield f"data: {json.dumps(chunk_dict)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            logger.exception(f"Error in LLM stream: {e}")
            error_data = {"error": {"message": "An internal error has occurred.", "type": "internal_error"}}
            yield f"data: {json.dumps(error_data)}\n\n".encode()

    def _create_streaming_response(self, async_generator: AsyncGenerator[bytes, None]) -> StreamingHttpResponse:
        streaming_content = (
            async_generator if settings.SERVER_GATEWAY_INTERFACE == "ASGI" else async_to_sync(lambda: async_generator)
        )
        response = StreamingHttpResponse(streaming_content, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    @extend_schema(
        summary="Anthropic Messages API",
        description="Create a message using Anthropic's Claude models. Compatible with Anthropic's Messages API format.",
        request=AnthropicMessagesRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=AnthropicMessagesResponseSerializer, description="Successful response with generated message"
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid request parameters"),
            500: OpenApiResponse(response=ErrorResponseSerializer, description="Internal server error"),
        },
        examples=[
            OpenApiExample(
                "Basic Request",
                description="Simple message request",
                value={
                    "model": "claude-3-5-sonnet-20241022",
                    "messages": [{"role": "user", "content": "Hello, Claude!"}],
                    "max_tokens": 1024,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Streaming Request",
                description="Request with streaming enabled",
                value={
                    "model": "claude-3-5-sonnet-20241022",
                    "messages": [{"role": "user", "content": "Write a haiku"}],
                    "max_tokens": 1024,
                    "stream": True,
                },
                request_only=True,
            ),
        ],
        tags=["LLM Gateway"],
    )
    @action(detail=False, methods=["POST"], url_path="v1/messages", required_scopes=["task:write"])
    def anthropic_messages(self, request: Request, *args, **kwargs):
        serializer = AnthropicMessagesRequestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"error": {"message": str(serializer.errors), "type": "invalid_request_error"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = dict(serializer.validated_data)
        is_streaming = data.get("stream", False)

        if is_streaming:
            sse_stream = self._format_as_sse(self._anthropic_stream(data), request)
            return self._create_streaming_response(sse_stream)
        else:
            try:
                response = asyncio.run(litellm.anthropic_messages(**data))
                response_dict = response.model_dump() if hasattr(response, "model_dump") else response
                return Response(response_dict)
            except Exception as e:
                logger.exception(f"Error in Anthropic messages endpoint: {e}")
                error_response = {
                    "error": {
                        "message": getattr(e, "message", str(e)),
                        "type": getattr(e, "type", "internal_error"),
                        "code": getattr(e, "code", None),
                    }
                }
                status_code = getattr(e, "status_code", 500)
                return Response(error_response, status=status_code)

    @extend_schema(
        summary="OpenAI Chat Completions API",
        description="Create a chat completion using OpenAI or compatible models. Follows OpenAI's Chat Completions API format.",
        request=ChatCompletionRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ChatCompletionResponseSerializer, description="Successful response with chat completion"
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid request parameters"),
            500: OpenApiResponse(response=ErrorResponseSerializer, description="Internal server error"),
        },
        examples=[
            OpenApiExample(
                "Basic Request",
                description="Simple chat completion request",
                value={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello!"}],
                },
                request_only=True,
            ),
            OpenApiExample(
                "Streaming Request",
                description="Request with streaming enabled",
                value={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Write a short poem"}],
                    "stream": True,
                    "temperature": 0.7,
                },
                request_only=True,
            ),
        ],
        tags=["LLM Gateway"],
    )
    @action(
        detail=False,
        methods=["POST"],
        url_path="v1/chat/completions",
        required_scopes=["task:write"],
    )
    def chat_completions(self, request: Request, *args, **kwargs):
        serializer = ChatCompletionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": {"message": str(serializer.errors), "type": "invalid_request_error"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = dict(serializer.validated_data)
        is_streaming = data.get("stream", False)

        if is_streaming:
            sse_stream = self._format_as_sse(self._openai_stream(data), request)
            return self._create_streaming_response(sse_stream)
        else:
            try:
                response = asyncio.run(litellm.acompletion(**data))
                response_dict = response.model_dump() if hasattr(response, "model_dump") else response
                return Response(response_dict)
            except Exception as e:
                logger.exception(f"Error in chat completions endpoint: {e}")
                error_response = {
                    "error": {
                        "message": getattr(e, "message", str(e)),
                        "type": getattr(e, "type", "internal_error"),
                        "code": getattr(e, "code", None),
                    }
                }
                status_code = getattr(e, "status_code", 500)
                return Response(error_response, status=status_code)
