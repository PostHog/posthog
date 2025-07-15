from __future__ import annotations

import hashlib
import json
from typing import Optional

from django.utils.crypto import get_random_string
import posthoganalytics
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import viewsets
from django.core.cache import cache
from rest_framework import serializers, exceptions
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionMessageParam,
)
from posthoganalytics.ai.openai import OpenAI
from posthoganalytics.ai.gemini import genai
from google.genai.types import GenerateContentConfig, Schema

from posthog.rate_limit import SetupWizardQueryRateThrottle
from rest_framework.exceptions import AuthenticationFailed

from ..utils import action
from .utils import json_schema_to_gemini_schema

SETUP_WIZARD_CACHE_PREFIX = "setup-wizard:v1:"
SETUP_WIZARD_CACHE_TIMEOUT = 600
SETUP_WIZARD_DEFAULT_MODEL = "o4-mini"

OPENAI_SUPPORTED_MODELS = {
    "o4-mini",
}

# Supported Gemini models
GEMINI_SUPPORTED_MODELS = {
    "gemini-2.5-flash",
    "gemini-2.5-pro",
}

ALL_SUPPORTED_MODELS = OPENAI_SUPPORTED_MODELS | GEMINI_SUPPORTED_MODELS

MODEL_SEED = 7678464


class SetupWizardSerializer(serializers.Serializer):
    hash = serializers.CharField()

    def to_representation(self, instance: str) -> dict[str, str]:
        return {"hash": instance}

    def create(self, validated_data: Optional[dict[str, str]] = None) -> dict[str, str]:
        hash = get_random_string(64, allowed_chars="abcdefghijklmnopqrstuvwxyz0123456789")
        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"

        cache.set(key, {"project_api_key": None, "host": None}, SETUP_WIZARD_CACHE_TIMEOUT)

        return {"hash": hash}


class SetupWizardQuerySerializer(serializers.Serializer):
    message = serializers.CharField()
    json_schema = serializers.JSONField()
    model = serializers.CharField(default=SETUP_WIZARD_DEFAULT_MODEL)

    def validate_model(self, value):
        """Validate that the model is supported"""
        if value not in ALL_SUPPORTED_MODELS:
            raise serializers.ValidationError(
                f"Model '{value}' is not supported. Supported models: {ALL_SUPPORTED_MODELS}"
            )
        return value


class SetupWizardViewSet(viewsets.ViewSet):
    permission_classes = ()
    lookup_field = "hash"
    lookup_url_kwarg = "hash"

    @action(methods=["POST"], detail=False, url_path="initialize")
    def initialize(self, request: Request) -> Response:
        """
        This endpoint is used to initialize the setup wizard. It creates a unique hash for the user to authenticate themselves.
        """

        serializer = SetupWizardSerializer()

        return Response(serializer.create())

    @action(methods=["GET"], detail=False, url_path="data")
    def data(self, request: Request, hash=None) -> Response:
        """
        This endpoint is used to get the data for the setup wizard to use.
        """

        hash = request.headers.get("X-PostHog-Wizard-Hash")

        if not hash:
            raise AuthenticationFailed("X-PostHog-Wizard-Hash header is required.")

        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"

        wizard_data = cache.get(key)

        if wizard_data is None:
            return Response(status=404, data={"error": "Invalid hash."})

        if not wizard_data.get("project_api_key") or not wizard_data.get("host"):
            return Response(status=400, data={"error": "Setup wizard not authenticated. Please login first"})

        return Response(wizard_data)

    @action(methods=["POST"], detail=False, url_path="query", throttle_classes=[SetupWizardQueryRateThrottle])
    def query(self, request: Request) -> Response:
        """
        This endpoint acts as a proxy for the setup wizard when making AI calls.
        """

        from django.conf import settings

        serializer = SetupWizardQuerySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        validated_data = serializer.validated_data
        message = validated_data["message"]
        json_schema = validated_data["json_schema"]
        model = validated_data["model"]

        hash = request.headers.get("X-PostHog-Wizard-Hash")

        if not hash:
            raise AuthenticationFailed("X-PostHog-Wizard-Hash header is required.")

        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"
        wizard_data = cache.get(key)

        if wizard_data is None:
            raise AuthenticationFailed("Invalid hash.")

        if not wizard_data.get("project_api_key") or not wizard_data.get("host"):
            raise AuthenticationFailed("Setup wizard not authenticated. Please login first")

        posthog_client = posthoganalytics.default_client

        if not posthog_client:
            raise exceptions.ValidationError("PostHog client not found")

        distinct_id = wizard_data.get("user_distinct_id")
        trace_id = hashlib.sha256(hash.encode()).hexdigest()

        system_prompt = (
            "You are a PostHog setup wizard. Only answer messages about setting up PostHog and nothing else."
        )

        if model in GEMINI_SUPPORTED_MODELS:
            api_key = settings.GEMINI_API_KEY
            if not api_key:
                raise exceptions.ValidationError("GEMINI_API_KEY is not configured")

            client = genai.Client(api_key=api_key, posthog_client=posthog_client)

            converted_schema = json_schema_to_gemini_schema(json_schema)

            response_schema = Schema(**converted_schema)

            config = GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0,
                seed=MODEL_SEED,
                response_mime_type="application/json",
                response_schema=response_schema,
            )

            response = client.models.generate_content(
                model=model,
                contents=message,
                config=config,
                posthog_distinct_id=distinct_id,
                posthog_trace_id=trace_id,
                posthog_properties={
                    "ai_product": "wizard",
                    "ai_feature": "query",
                },
            )

            if not response.parsed:
                raise exceptions.ValidationError("Invalid response from Gemini")

            response_data = response.parsed

        elif model in OPENAI_SUPPORTED_MODELS:
            system_message = ChatCompletionSystemMessageParam(
                role="system",
                content=system_prompt,
            )

            user_message = ChatCompletionUserMessageParam(role="user", content=message)

            messages: list[ChatCompletionMessageParam] = [system_message, user_message]

            openai = OpenAI(posthog_client=posthog_client)

            result = openai.chat.completions.create(
                model=model,
                seed=MODEL_SEED,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": json_schema},  # type: ignore
                posthog_distinct_id=distinct_id,
                posthog_trace_id=trace_id,
                posthog_properties={
                    "ai_product": "wizard",
                    "ai_feature": "query",
                },
            )

            if (
                not result.choices
                or len(result.choices) == 0
                or not result.choices[0].message
                or not result.choices[0].message.content
            ):
                raise exceptions.ValidationError("Invalid response from OpenAI")

            try:
                response_data = json.loads(result.choices[0].message.content)
            except json.JSONDecodeError:
                raise exceptions.ValidationError("Invalid JSON response from OpenAI")

        else:
            raise exceptions.ValidationError(f"Model '{model}' is not supported.")

        return Response({"data": response_data})
