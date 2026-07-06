from __future__ import annotations

import json
import hashlib
from typing import cast

from django.conf import settings
from django.core.cache import cache
from django.utils.crypto import get_random_string

import posthoganalytics
from drf_spectacular.utils import extend_schema
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
from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication
from posthog.cloud_utils import get_api_host
from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.project import Project
from posthog.rate_limit import (
    SetupWizardAuthenticationRateThrottle,
    SetupWizardCloudRunBurstRateThrottle,
    SetupWizardCloudRunSustainedRateThrottle,
    SetupWizardQueryRateThrottle,
)
from posthog.user_permissions import UserPermissions

from products.tasks.backend.facade import api as tasks_facade

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


class SetupWizardCloudRunSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(
        help_text="ID of the PostHog project to integrate PostHog into. The authenticated user must have access to it."
    )
    repository = serializers.CharField(
        help_text=(
            "GitHub repository to set up PostHog in, as 'owner/repo' (e.g. 'posthog/posthog-js'). The user "
            "must have a connected GitHub integration with access to it."
        )
    )
    branch = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Base branch the wizard's pull request should target. Defaults to the repository's default branch.",
    )

    def validate_repository(self, value: str) -> str:
        repository = value.strip()
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise serializers.ValidationError("Repository must be in 'owner/repo' format.")
        return repository


class SetupWizardCloudRunResponseSerializer(serializers.Serializer):
    task_id = serializers.CharField(
        help_text="ID of the created task. Poll the tasks API for its status and the resulting pull request URL."
    )
    run_id = serializers.CharField(help_text="ID of the task's run.")
    status = serializers.CharField(help_text="Initial status of the run (e.g. 'queued').")


class SetupWizardViewSet(viewsets.ViewSet):
    # Actions authenticate themselves: initialize is open, data/query use the wizard hash, and the
    # session-only actions (authenticate, cloud_run) set their own authentication/permission classes.
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
        fixture_generation = request.headers.get("X-PostHog-Wizard-Fixture-Generation")
        trace_id = None

        if hash:
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

            distinct_id = wizard_data.get("user_distinct_id")

            trace_id = trace_id or hashlib.sha256(hash.encode()).hexdigest()

        else:
            result = OAuthAccessTokenAuthentication().authenticate(request)

            if not result:
                raise AuthenticationFailed("Invalid access token.")

            user, _ = result

            if not user:
                raise AuthenticationFailed("Invalid access token.")

            distinct_id = user.distinct_id

            trace_id = request.headers.get("X-PostHog-Trace-Id") or hashlib.sha256(distinct_id.encode()).hexdigest()

        posthog_client = posthoganalytics.default_client

        if not posthog_client:
            raise exceptions.ValidationError("PostHog client not found")

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
        authentication_classes=[SessionAuthentication],
        permission_classes=[IsAuthenticated],
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
            # nosemgrep: idor-lookup-without-org, idor-taint-user-input-to-org-model (permission check after lookup)
            project = Project.objects.get(id=project_id)

            # Verify user has access to this project
            visible_project_ids = UserPermissions(request.user).project_ids_visible_for_user
            if project.id not in visible_project_ids:
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

    @extend_schema(
        request=SetupWizardCloudRunSerializer,
        responses={200: SetupWizardCloudRunResponseSerializer},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="cloud_run",
        authentication_classes=[SessionAuthentication],
        permission_classes=[IsAuthenticated],
        throttle_classes=[SetupWizardCloudRunBurstRateThrottle, SetupWizardCloudRunSustainedRateThrottle],
    )
    def cloud_run(self, request: Request) -> Response:
        """Run the PostHog setup wizard in the cloud against the user's GitHub repository.

        Provisions a task-run sandbox that runs the published wizard headlessly to integrate PostHog,
        then hands off to the task agent to open the pull request and keep it green. The wizard
        authenticates with a dedicated, scoped token minted under the wizard's own OAuth app — distinct
        from the agent's sandbox token. This is the cloud alternative to copy-pasting the wizard command
        to run locally; it is intentionally rate limited heavily because each run starts a sandbox.
        """
        if not bool(settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID):
            raise exceptions.NotFound("Running the setup wizard in the cloud is not available.")

        serializer = SetupWizardCloudRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project_id = serializer.validated_data["project_id"]
        repository = serializer.validated_data["repository"]
        branch = serializer.validated_data.get("branch") or None

        visible_project_ids = UserPermissions(cast(User, request.user)).project_ids_visible_for_user
        try:
            # nosemgrep: idor-lookup-without-org, idor-taint-user-input-to-org-model (permission check below)
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            raise serializers.ValidationError({"project_id": [ERROR_PROJECT_NOT_FOUND]}, code="not_found")
        if project.id not in visible_project_ids:
            raise exceptions.PermissionDenied("You don't have access to this project.")

        try:
            result = tasks_facade.create_wizard_cloud_run(
                team=project.passthrough_team,
                user_id=cast(User, request.user).id,
                repository=repository,
                branch=branch,
            )
        except ValueError as e:
            # e.g. the team/user has no GitHub integration with access to the repository.
            raise exceptions.ValidationError(str(e))

        latest_run = result.latest_run
        return Response(
            {
                "task_id": str(result.task_id),
                "run_id": str(latest_run.id) if latest_run else "",
                "status": latest_run.status if latest_run else "queued",
            }
        )
