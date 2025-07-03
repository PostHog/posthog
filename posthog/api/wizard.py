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

from posthog.rate_limit import SetupWizardQueryRateThrottle
from rest_framework.exceptions import AuthenticationFailed

from .utils import action

SETUP_WIZARD_CACHE_PREFIX = "setup-wizard:v1:"
SETUP_WIZARD_CACHE_TIMEOUT = 600
SETUP_WIZARD_MODEL = "o4-mini"


class SetupWizardSerializer(serializers.Serializer):
    hash = serializers.CharField()

    def to_representation(self, instance: str) -> dict[str, str]:
        return {"hash": instance}

    def create(self, validated_data: Optional[dict[str, str]] = None) -> dict[str, str]:
        hash = get_random_string(64, allowed_chars="abcdefghijklmnopqrstuvwxyz0123456789")
        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"

        cache.set(key, {"project_api_key": None, "host": None}, SETUP_WIZARD_CACHE_TIMEOUT)

        return {"hash": hash}


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
        This endpoint acts as a proxy for the setup wizard when making OpenAI calls.
        """

        message = request.data.get("message")
        json_schema = request.data.get("json_schema")
        hash = request.headers.get("X-PostHog-Wizard-Hash")

        if not hash:
            raise AuthenticationFailed("X-PostHog-Wizard-Hash header is required.")

        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"
        wizard_data = cache.get(key)

        if wizard_data is None:
            raise AuthenticationFailed("Invalid hash.")

        if not wizard_data.get("project_api_key") or not wizard_data.get("host"):
            raise AuthenticationFailed("Setup wizard not authenticated. Please login first")

        if not message or not json_schema:
            return Response({"error": "Both message and json_schema are required."}, status=400)

        # Create system prompt
        system_message = ChatCompletionSystemMessageParam(
            role="system",
            content="You are a PostHog setup wizard. Only answer messages about setting up PostHog and nothing else.",
        )

        user_message = ChatCompletionUserMessageParam(role="user", content=message)

        # Convert messages to OpenAI format and combine with system message
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]

        posthog_client = posthoganalytics.default_client

        if not posthog_client:
            raise exceptions.ValidationError("PostHog client not found")

        openai = OpenAI(posthog_client=posthog_client)

        distinct_id = wizard_data.get("user_distinct_id")

        trace_id = hashlib.sha256(hash.encode()).hexdigest()

        result = openai.chat.completions.create(
            model=SETUP_WIZARD_MODEL,
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

        return Response({"data": response_data})
