from __future__ import annotations


from rest_framework import viewsets, serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from posthoganalytics.ai.openai import OpenAI
import posthoganalytics
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
)

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import TeamMemberAccessPermission
from posthog.rate_limit import LLMPlaygroundRateThrottle

DEFAULT_MODELS = [
    {"id": "o1-mini", "name": "O1-Mini", "provider": "Anthropic", "description": "Fast, compact model for general use"},
    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "OpenAI", "description": "Fast model for most tasks"},
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "OpenAI", "description": "Advanced reasoning capabilities"},
]


class LLMPlaygroundSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=True)
    model = serializers.CharField(required=True)
    temperature = serializers.FloatField(required=False, default=0.7, min_value=0, max_value=1)
    max_tokens = serializers.IntegerField(required=False, default=1024, min_value=1, max_value=8192)
    system_prompt = serializers.CharField(required=False, default="You are a helpful assistant.")
    messages = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class LLMPlaygroundViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, TeamMemberAccessPermission]
    throttle_classes = [LLMPlaygroundRateThrottle]
    scope_object = "feature_flag"  # Using a similar scope to other features
    param_derived_from_user_current_team = "team_id"  # Use the user's current team

    @action(methods=["GET"], detail=False)
    def models(self, request: Request, **kwargs) -> Response:
        """Return a list of available models"""
        # In a production environment, this would likely be dynamic based on API keys and available providers
        return Response(DEFAULT_MODELS)

    @action(methods=["POST"], detail=False)
    def generate(self, request: Request, **kwargs) -> Response:
        """Generate a response from an LLM"""
        serializer = LLMPlaygroundSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        data = serializer.validated_data

        # Create messages for the OpenAI API
        messages: list[ChatCompletionMessageParam] = []

        # Add system prompt if provided
        if data.get("system_prompt"):
            messages.append(ChatCompletionSystemMessageParam(role="system", content=data["system_prompt"]))

        # Add previous messages if provided
        for message in data.get("messages", []):
            if message["role"] == "user":
                messages.append(ChatCompletionUserMessageParam(role="user", content=message["content"]))
            elif message["role"] == "assistant":
                messages.append(ChatCompletionAssistantMessageParam(role="assistant", content=message["content"]))

        # Add the current prompt
        messages.append(ChatCompletionUserMessageParam(role="user", content=data["prompt"]))

        posthog_client = posthoganalytics.default_client
        if not posthog_client:
            return Response({"error": "PostHog analytics client not configured"}, status=500)

        openai = OpenAI(posthog_client=posthog_client)

        try:
            # Create the request parameters - handling distinct_id and properties separately
            # request_params = {
            #     "model": data["model"],
            #     "messages": messages,
            #     "temperature": data.get("temperature", 0.7),
            #     "max_tokens": data.get("max_tokens", 1024),
            # }

            # # Add PostHog-specific parameters
            # distinct_id = getattr(request.user, "distinct_id", str(request.user.pk))
            # posthog_properties = {
            #     "ai_product": "llm_playground",
            #     "ai_feature": "generate",
            #     "team_id": team.pk,  # Use .pk instead of .id
            # }

            result = openai.chat.completions.create(
                model=data["model"],
                messages=messages,
                temperature=data.get("temperature", 0.7),
                max_tokens=data.get("max_tokens", 1024),
            )

            if not result.choices or not result.choices[0].message:
                return Response({"error": "No response from model"}, status=500)

            response_data = {
                "text": result.choices[0].message.content,
                "model": data["model"],
                "usage": {
                    "prompt_tokens": result.usage.prompt_tokens if result.usage else None,
                    "completion_tokens": result.usage.completion_tokens if result.usage else None,
                    "total_tokens": result.usage.total_tokens if result.usage else None,
                },
            }

            return Response(response_data)

        except Exception as e:
            return Response({"error": str(e)}, status=500)
