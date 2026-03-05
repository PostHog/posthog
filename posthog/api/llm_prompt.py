from typing import Any, cast

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q, QuerySet, TextField
from django.db.models.functions import Cast

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.capture import capture_internal
from posthog.api.llm_prompt_serializers import (
    LLMPromptFetchQuerySerializer,
    LLMPromptPublicSerializer,
    LLMPromptPublishSerializer,
    LLMPromptResolveQuerySerializer,
    LLMPromptResolveResponseSerializer,
    LLMPromptSerializer,
    LLMPromptVersionSummarySerializer,
)
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.llm_prompt import (
    LLMPromptNotFoundError,
    LLMPromptVersionConflictError,
    LLMPromptVersionLimitError,
    archive_prompt,
    get_active_prompt_queryset,
    get_latest_prompts_queryset,
    get_prompt_by_name_from_db,
    publish_prompt_version,
    resolve_versions_page,
)
from posthog.auth import JwtAuthentication, SessionAuthentication
from posthog.event_usage import report_team_action, report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import LLMPrompt, User
from posthog.permissions import AccessControlPermission, get_organization_from_view
from posthog.rate_limit import BurstRateThrottle, LLMPromptPublishBurstRateThrottle, SustainedRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

from products.llm_analytics.backend.api.metrics import llma_track_latency

PROMPT_FETCHED_EVENT = "$llm_prompt_fetched"
PROMPT_FETCHED_EVENT_SOURCE = "llm_prompt_management"
LLM_PROMPT_FEATURE_FLAGS = ("prompt-management", "llm-analytics-early-adopters")
ALLOWED_LIST_ORDERINGS = {
    "name": "name",
    "-name": "-name",
    "created_at": "created_at",
    "-created_at": "-created_at",
    "updated_at": "updated_at",
    "-updated_at": "-updated_at",
    "version": "version",
    "-version": "-version",
    "latest_version": "latest_version",
    "-latest_version": "-latest_version",
    "version_count": "version_count",
    "-version_count": "-version_count",
    "first_version_created_at": "first_version_created_at",
    "-first_version_created_at": "-first_version_created_at",
}


class LLMPromptFeatureFlagPermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = cast(User, request.user)
        organization = get_organization_from_view(view)
        org_id = str(organization.id)
        distinct_id = user.distinct_id or str(user.uuid)

        return any(
            posthoganalytics.feature_enabled(
                feature_flag,
                distinct_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
            for feature_flag in LLM_PROMPT_FEATURE_FLAGS
        )


class LLMPromptViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "llm_prompt"
    queryset = LLMPrompt.objects.all()
    serializer_class = LLMPromptSerializer
    permission_classes = [LLMPromptFeatureFlagPermission, AccessControlPermission]

    def safely_get_queryset(self, queryset: QuerySet[LLMPrompt]) -> QuerySet[LLMPrompt]:
        return get_active_prompt_queryset(self.team)

    def get_throttles(self):
        if self.action == "update_by_name":
            return [LLMPromptPublishBurstRateThrottle(), BurstRateThrottle(), SustainedRateThrottle()]
        if self.action in ["get_by_name", "resolve_by_name"]:
            return [BurstRateThrottle(), SustainedRateThrottle()]

        return super().get_throttles()

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        super_method = getattr(super(), "dangerously_get_required_scopes", None)
        if callable(super_method):
            mixin_result = super_method(request, view)
            if mixin_result is not None:
                return mixin_result

        if view.action in ["get_by_name", "update_by_name"]:
            return ["llm_prompt:write"] if request.method == "PATCH" else ["llm_prompt:read"]
        return None

    def _ensure_web_authenticated(self, request: Request) -> Response | None:
        if not isinstance(request.successful_authenticator, SessionAuthentication | JwtAuthentication):
            return Response(
                {"detail": "This endpoint is only available to web-authenticated users."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def _prompt_not_found_response(self, prompt_name: str) -> Response:
        return Response(
            {"detail": f"Prompt with name '{prompt_name}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    def _serialize_prompt(self, prompt: LLMPrompt) -> dict[str, Any]:
        return cast(dict[str, Any], self.get_serializer(prompt).data)

    def _serialize_version_summaries(self, prompts: list[LLMPrompt]) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], LLMPromptVersionSummarySerializer(prompts, many=True).data)

    def _get_requested_version_params(self, request: Request) -> dict[str, Any]:
        serializer = LLMPromptFetchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _get_resolve_query_params(self, request: Request) -> dict[str, Any]:
        serializer = LLMPromptResolveQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _track_prompt_fetch(self, prompt: dict[str, Any]) -> None:
        if not settings.TEST:
            try:
                capture_internal(
                    token=self.team.api_token,
                    event_name=PROMPT_FETCHED_EVENT,
                    event_source=PROMPT_FETCHED_EVENT_SOURCE,
                    distinct_id=str(self.team.uuid),
                    timestamp=None,
                    properties={
                        "prompt_id": prompt["id"],
                        "prompt_name": prompt["name"],
                        "prompt_version": prompt["version"],
                        "prompt_is_latest": prompt["is_latest"],
                        "prompt_first_version_created_at": prompt["first_version_created_at"],
                    },
                )
            except Exception as err:
                capture_exception(err)

        report_team_action(
            self.team,
            "llma prompt fetched",
            {
                "prompt_id": prompt["id"],
                "prompt_name": prompt["name"],
                "prompt_version": prompt["version"],
                "prompt_is_latest": prompt["is_latest"],
                "prompt_first_version_created_at": prompt["first_version_created_at"],
            },
        )

    def _get_list_queryset(self, request: Request) -> QuerySet[LLMPrompt]:
        queryset = get_latest_prompts_queryset(self.team)

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.annotate(prompt_text=Cast("prompt", output_field=TextField())).filter(
                Q(name__icontains=search) | Q(prompt_text__icontains=search)
            )

        order_by = request.query_params.get("order_by", "-created_at")
        queryset = queryset.order_by(ALLOWED_LIST_ORDERINGS.get(order_by, "-created_at"), "-id")
        return queryset

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        instance = cast(LLMPrompt, serializer.save())

        report_user_action(
            cast(User, self.request.user),
            "llma prompt created",
            {
                "prompt_id": str(instance.id),
                "prompt_name": instance.name,
                "prompt_version": instance.version,
            },
            team=self.team,
            request=self.request,
        )

    @extend_schema(
        parameters=[LLMPromptFetchQuerySerializer],
        responses={200: LLMPromptPublicSerializer},
    )
    @action(methods=["GET"], detail=False, url_path=r"name/(?P<prompt_name>[^/]+)")
    @llma_track_latency("llma_prompts_get_by_name")
    @monitor(feature=None, endpoint="llma_prompts_get_by_name", method="GET")
    def get_by_name(self, request: Request, prompt_name: str = "", **kwargs) -> Response:
        version_params = self._get_requested_version_params(request)
        version = cast(int | None, version_params.get("version"))
        prompt = get_prompt_by_name_from_cache(self.team, prompt_name, version)
        if prompt is None:
            return self._prompt_not_found_response(prompt_name)

        self._track_prompt_fetch(prompt)
        return Response(prompt)

    @extend_schema(request=LLMPromptPublishSerializer, responses={200: LLMPromptSerializer})
    @get_by_name.mapping.patch
    @llma_track_latency("llma_prompts_publish_by_name")
    @monitor(feature=None, endpoint="llma_prompts_publish_by_name", method="PATCH")
    def update_by_name(self, request: Request, prompt_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        payload = LLMPromptPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            published_prompt = publish_prompt_version(
                self.team,
                user=cast(User, request.user),
                prompt_name=prompt_name,
                prompt_payload=payload.validated_data["prompt"],
                base_version=payload.validated_data["base_version"],
            )
        except LLMPromptNotFoundError:
            return self._prompt_not_found_response(prompt_name)
        except LLMPromptVersionConflictError as err:
            return Response(
                {
                    "detail": "The prompt changed since you opened it. Reload the latest version and try again.",
                    "current_version": err.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except LLMPromptVersionLimitError as err:
            return Response(
                {
                    "detail": (
                        f"Prompt has reached the maximum of {err.max_version} versions. "
                        "Archive and recreate the prompt to continue publishing."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        report_user_action(
            cast(User, request.user),
            "llma prompt version published",
            {
                "prompt_id": str(published_prompt.id),
                "prompt_name": published_prompt.name,
                "prompt_version": published_prompt.version,
                "base_version": payload.validated_data["base_version"],
            },
            team=self.team,
            request=request,
        )
        return Response(self._serialize_prompt(published_prompt))

    @extend_schema(parameters=[LLMPromptResolveQuerySerializer], responses={200: LLMPromptResolveResponseSerializer})
    @action(
        methods=["GET"],
        detail=False,
        url_path=r"resolve/name/(?P<prompt_name>[^/]+)",
        required_scopes=["llm_prompt:read"],
    )
    @llma_track_latency("llma_prompts_resolve_by_name")
    @monitor(feature=None, endpoint="llma_prompts_resolve_by_name", method="GET")
    def resolve_by_name(self, request: Request, prompt_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        query_params = self._get_resolve_query_params(request)
        version = cast(int | None, query_params.get("version"))
        version_id = query_params.get("version_id")
        prompt = get_prompt_by_name_from_db(
            self.team,
            prompt_name=prompt_name,
            version=version,
            version_id=str(version_id) if version_id else None,
        )
        if prompt is None:
            return self._prompt_not_found_response(prompt_name)

        limit = cast(int, query_params["limit"])
        offset = cast(int | None, query_params.get("offset"))
        before_version = cast(int | None, query_params.get("before_version"))
        versions, has_more = resolve_versions_page(
            self.team,
            prompt_name=prompt_name,
            limit=limit,
            offset=offset,
            before_version=before_version,
        )
        return Response(
            {
                "prompt": self._serialize_prompt(prompt),
                "versions": self._serialize_version_summaries(versions),
                "has_more": has_more,
            }
        )

    @action(
        methods=["POST"],
        detail=False,
        url_path=r"name/(?P<prompt_name>[^/]+)/archive",
        required_scopes=["llm_prompt:write"],
    )
    @llma_track_latency("llma_prompts_archive")
    @monitor(feature=None, endpoint="llma_prompts_archive", method="POST")
    def archive(self, request: Request, prompt_name: str = "", **kwargs) -> Response:
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        try:
            prompt_versions = archive_prompt(self.team, prompt_name)
        except LLMPromptNotFoundError:
            return self._prompt_not_found_response(prompt_name)

        report_user_action(
            cast(User, request.user),
            "llma prompt archived",
            {
                "prompt_name": prompt_name,
                "prompt_versions": prompt_versions,
            },
            team=self.team,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @llma_track_latency("llma_prompts_list")
    @monitor(feature=None, endpoint="llma_prompts_list", method="GET")
    def list(self, request: Request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self._get_list_queryset(request))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        return Response({"count": len(data), "results": data})

    @llma_track_latency("llma_prompts_create")
    @monitor(feature=None, endpoint="llma_prompts_create", method="POST")
    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as err:
            if any(
                constraint_name in str(err)
                for constraint_name in ["unique_llm_prompt_latest_per_team", "unique_llm_prompt_version_per_team"]
            ):
                raise serializers.ValidationError({"name": "A prompt with this name already exists."}, code="unique")
            raise
