from __future__ import annotations

import json
import hashlib

from django.core.cache import cache
from django.utils.crypto import get_random_string

import posthoganalytics
from google.genai.types import GenerateContentConfig, Schema
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from posthoganalytics.ai.gemini import genai
from posthoganalytics.ai.openai import OpenAI
from rest_framework import exceptions, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.wizard.utils import json_schema_to_gemini_schema
from posthog.cloud_utils import get_api_host
from posthog.exceptions_capture import capture_exception
from posthog.models.project import Project
from posthog.permissions import APIScopePermission
from posthog.rate_limit import SetupWizardAuthenticationRateThrottle, SetupWizardQueryRateThrottle
from posthog.user_permissions import UserPermissions

SETUP_WIZARD_CACHE_PREFIX = "setup-wizard:v1:"
SETUP_WIZARD_CACHE_TIMEOUT = 600
SETUP_WIZARD_DEFAULT_MODEL = "gpt-5-mini"

ERROR_GEMINI_API_KEY_NOT_CONFIGURED = "GEMINI_API_KEY is not configured"
ERROR_INVALID_GEMINI_RESPONSE = "Invalid response from Gemini"
ERROR_INVALID_OPENAI_JSON = "Invalid JSON response from OpenAI"
ERROR_PROJECT_NOT_FOUND = "This project does not exist."

OPENAI_SUPPORTED_MODELS = {"o4-mini", "gpt-5-mini", "gpt-5-nano", "gpt-5"}

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

    def create(self, validated_data: dict[str, str] | None = None) -> dict[str, str]:
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

    def dangerously_get_permissions(self):
        # API Level permissions are only required during the authentication step.
        # For all other actions we use a cache key to authenticate.
        if self.action == "authenticate":
            return [IsAuthenticated(), APIScopePermission()]

        raise NotImplementedError()

    def dangerously_get_required_scopes(self):
        if self.action == "authenticate":
            return ["project:read"]

        return []

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
        fixture_generation = request.headers.get("X-PostHog-Wizard-Fixture-Generation")

        if not hash:
            raise AuthenticationFailed("X-PostHog-Wizard-Hash header is required.")

        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"
        wizard_data = cache.get(key)

        # wizard_data should only be mocked during the @posthog/wizard E2E tests, so that fixtures can be generated.
        mock_wizard_data = settings.DEBUG and fixture_generation

        if mock_wizard_data:
            wizard_data = {
                "project_api_key": "mock-project-api-key",
                "host": "http://localhost:8010",
                "user_distinct_id": "mock-user-id",
            }
            cache.set(key, wizard_data, SETUP_WIZARD_CACHE_TIMEOUT)

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
                error = exceptions.ValidationError(ERROR_GEMINI_API_KEY_NOT_CONFIGURED)
                capture_exception(
                    error,
                    {
                        "model": model,
                        "ai_product": "wizard",
                        "team": "growth",
                    },
                )
                raise error

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
                error = exceptions.ValidationError(ERROR_INVALID_GEMINI_RESPONSE)
                capture_exception(
                    error,
                    {
                        "model": model,
                        "ai_product": "wizard",
                        "team": "growth",
                        "trace_id": trace_id,
                        "distinct_id": distinct_id,
                    },
                )
                raise error

            response_data = response.parsed

        elif model in OPENAI_SUPPORTED_MODELS:
            system_message = ChatCompletionSystemMessageParam(
                role="system",
                content=system_prompt,
            )

            user_message = ChatCompletionUserMessageParam(role="user", content=message)

            messages: list[ChatCompletionMessageParam] = [system_message, user_message]

            openai = OpenAI(posthog_client=posthog_client, base_url=settings.OPENAI_BASE_URL)

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
                temperature=1.0,
            )

            if (
                not result.choices
                or len(result.choices) == 0
                or not result.choices[0].message
                or not result.choices[0].message.content
            ):
                raise exceptions.ValidationError(ERROR_INVALID_OPENAI_JSON)

            try:
                response_data = json.loads(result.choices[0].message.content)
            except json.JSONDecodeError as e:
                capture_exception(
                    e,
                    {
                        "model": model,
                        "ai_product": "wizard",
                        "team": "growth",
                        "trace_id": trace_id,
                        "distinct_id": distinct_id,
                        "response_content": result.choices[0].message.content[:500]
                        if result.choices[0].message.content
                        else None,
                    },
                )
                raise exceptions.ValidationError(ERROR_INVALID_OPENAI_JSON)

        else:
            raise exceptions.ValidationError(f"Model '{model}' is not supported.")

        return Response({"data": response_data})

    @action(
        methods=["POST"],
        url_path="authenticate",
        detail=False,
        throttle_classes=[SetupWizardAuthenticationRateThrottle],
    )
    def authenticate(self, request, **kwargs):
        hash = request.data.get("hash")
        project_id = request.data.get("projectId")

        if not hash:
            raise serializers.ValidationError({"hash": ["This field is required."]}, code="required")

        if not project_id:
            raise serializers.ValidationError({"projectId": ["This field is required."]}, code="required")

        cache_key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"
        wizard_data = cache.get(cache_key)

        if wizard_data is None:
            raise serializers.ValidationError({"hash": ["This hash is invalid or has expired."]}, code="invalid_hash")

        try:
            project = Project.objects.get(id=project_id)

            # Verify user has access to this project
            visible_teams_ids = UserPermissions(request.user).team_ids_visible_for_user
            if project.id not in visible_teams_ids:
                raise serializers.ValidationError(
                    {"projectId": ["You don't have access to this project."]}, code="permission_denied"
                )

            project_api_token = project.passthrough_team.api_token
        except Project.DoesNotExist as e:
            capture_exception(
                e,
                {
                    "project_id": project_id,
                    "user_id": request.user.id if request.user else None,
                    "user_distinct_id": request.user.distinct_id if request.user else None,
                    "ai_product": "wizard",
                    "team": "growth",
                },
            )
            raise serializers.ValidationError({"projectId": [ERROR_PROJECT_NOT_FOUND]}, code="not_found")

        wizard_data = {
            "project_api_key": project_api_token,
            "host": get_api_host(),
            "user_distinct_id": request.user.distinct_id,
        }

        cache.set(cache_key, wizard_data, SETUP_WIZARD_CACHE_TIMEOUT)

        return response.Response({"success": True}, status=200)
