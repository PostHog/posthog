import json
import logging
from collections.abc import AsyncGenerator, Generator

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
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission
from posthog.rate_limit import LLMGatewayBurstRateThrottle, LLMGatewaySustainedRateThrottle
from posthog.renderers import SafeJSONRenderer, ServerSentEventRenderer
from posthog.settings import SERVER_GATEWAY_INTERFACE

from ee.hogai.utils.asgi import SyncIterableToAsync

from .serializers import (
    AnthropicMessagesRequestSerializer,
    AnthropicMessagesResponseSerializer,
    ChatCompletionRequestSerializer,
    ChatCompletionResponseSerializer,
    ErrorResponseSerializer,
)

logger = logging.getLogger(__name__)

SCOPE_OBJECT = "task"


class LLMGatewayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = SCOPE_OBJECT
    renderer_classes = [SafeJSONRenderer, ServerSentEventRenderer]

    def get_throttles(self):
        return [LLMGatewayBurstRateThrottle(), LLMGatewaySustainedRateThrottle()]

    async def _stream_response(self, response, request: Request) -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in response:
                if not request.META.get("SERVER_NAME"):
                    return
                chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                yield f"data: {json.dumps(chunk_dict)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            logger.exception(f"Error in LLM gateway stream: {e}")
            error_data = {"error": {"message": "An internal error occurred", "type": "internal_error"}}
            yield f"data: {json.dumps(error_data)}\n\n".encode()

    def _create_streaming_response(
        self, stream: AsyncGenerator[bytes, None] | Generator[bytes, None, None]
    ) -> StreamingHttpResponse:
        if SERVER_GATEWAY_INTERFACE == "ASGI":
            response = StreamingHttpResponse(streaming_content=stream, content_type=ServerSentEventRenderer.media_type)
        else:
            astream = SyncIterableToAsync(stream)
            response = StreamingHttpResponse(streaming_content=astream, content_type=ServerSentEventRenderer.media_type)
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
    @action(detail=False, methods=["POST"], url_path="v1/messages", required_scopes=f"{SCOPE_OBJECT}:write")
    async def anthropic_messages(self, request: Request, *args, **kwargs):
        try:
            serializer = AnthropicMessagesRequestSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": {"message": str(serializer.errors), "type": "invalid_request_error"}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            data = dict(serializer.validated_data)
            is_streaming = data.get("stream", False)

            if is_streaming:
                response = await litellm.anthropic_messages(**data)
                stream_gen = self._stream_response(response, request)
                return self._create_streaming_response(stream_gen)
            else:
                response = await litellm.anthropic_messages(**data)
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
        required_scopes=f"{SCOPE_OBJECT}:write",
    )
    async def chat_completions(self, request: Request, *args, **kwargs):
        try:
            serializer = ChatCompletionRequestSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": {"message": str(serializer.errors), "type": "invalid_request_error"}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            data = dict(serializer.validated_data)
            is_streaming = data.get("stream", False)

            if is_streaming:
                response = await litellm.acompletion(**data)
                stream_gen = self._stream_response(response, request)
                return self._create_streaming_response(stream_gen)
            else:
                response = await litellm.acompletion(**data)
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
