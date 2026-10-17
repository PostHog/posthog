import math
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import posthog_feature_flag_enabled

from products.aeo.backend.facade.api import get_prompt, import_prompts, list_prompts, set_prompt_active
from products.aeo.backend.facade.contracts import (
    AEO_CITATION_TRACKING_FLAG,
    PROMPT_TOPIC_MAX_LENGTH,
    Prompt,
    PromptImport,
    PromptImportResult,
    PromptNotFoundError,
)

MAX_PROMPTS_PER_IMPORT = 2000
DEFAULT_PAGE_SIZE = 100
# Bounds the request body. Prompts longer than the engines accept are counted as skipped, not rejected.
MAX_IMPORTED_PROMPT_CHARS = 10_000

EXTERNAL_VISIBILITY_HELP = (
    "Share of answers (0-100) that mention the brand for this prompt, as reported by the tool the prompt set "
    "came from. Kept to benchmark against our own citation rate."
)


class AEOPromptSerializer(DataclassSerializer):
    class Meta:
        dataclass = Prompt
        ref_name = "AEOPrompt"
        extra_kwargs = {
            "id": {"help_text": "Prompt id."},
            "prompt": {"help_text": "The question asked to the answer engines, as a user would phrase it."},
            "topic": {"help_text": "Theme the prompt belongs to. The runner alternates between topics on each run."},
            "prompt_source": {"help_text": "Where the prompt came from: 'imported' or 'manual'."},
            "rank": {"help_text": "Seeding score. Within a topic, higher runs first."},
            "active": {"help_text": "Only active prompts are run against the answer engines."},
            "last_checked_at": {"help_text": "When the runner last ran this prompt. Null when it never ran."},
            "external_visibility": {"help_text": EXTERNAL_VISIBILITY_HELP + " Null when the import carried none."},
            "created_at": {"help_text": "When the prompt was added."},
            "updated_at": {"help_text": "When the prompt last changed."},
        }


class AEOPromptUpdateRequestSerializer(serializers.Serializer):
    active = serializers.BooleanField(help_text="Turn the prompt on or off for future runs.")


class AEOPromptImportItemSerializer(DataclassSerializer):
    class Meta:
        dataclass = PromptImport
        ref_name = "AEOPromptImport"
        extra_kwargs = {
            "prompt": {
                "allow_blank": True,
                "max_length": MAX_IMPORTED_PROMPT_CHARS,
                "help_text": "The question to ask the answer engines, as a user would phrase it. Matching ignores case and whitespace, so a re-import updates the existing prompt.",
            },
            "topic": {
                "max_length": PROMPT_TOPIC_MAX_LENGTH,
                "allow_blank": True,
                "help_text": "Theme the prompt belongs to. The runner alternates between topics on each run.",
            },
            "external_visibility": {"min_value": 0, "max_value": 100, "help_text": EXTERNAL_VISIBILITY_HELP},
        }

    def validate_external_visibility(self, value: float | None) -> float | None:
        # DRF parses "NaN" and "Infinity" as floats, and NaN passes both bounds checks.
        if value is not None and not math.isfinite(value):
            raise serializers.ValidationError("Must be a finite number between 0 and 100.")
        return value


class AEOPromptBulkImportRequestSerializer(serializers.Serializer):
    prompts = serializers.ListField(
        child=AEOPromptImportItemSerializer(),
        min_length=1,
        max_length=MAX_PROMPTS_PER_IMPORT,
        help_text=f"Prompts to add or update, at most {MAX_PROMPTS_PER_IMPORT} per request.",
    )


class AEOPromptImportResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = PromptImportResult
        ref_name = "AEOPromptImportResult"
        extra_kwargs = {
            "created": {"help_text": "Prompts added to the set."},
            "updated": {"help_text": "Existing prompts that were updated. They keep their active state."},
            "skipped": {"help_text": "Prompts that were empty or too long for the answer engines."},
        }


class AEOPromptViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["partial_update", "bulk_import"]
    pagination_class = PrecountedLimitOffsetPagination

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        distinct_id = getattr(request.user, "distinct_id", None)
        if not distinct_id or not posthog_feature_flag_enabled(
            AEO_CITATION_TRACKING_FLAG, distinct_id, organization_id=self.organization_id
        ):
            raise PermissionDenied("This feature is not available.")

    @extend_schema(
        operation_id="aeo_prompts_list",
        summary="List AEO prompts",
        description="Lists the project's AEO prompt set, grouped by topic, one page at a time.",
        responses={200: AEOPromptSerializer(many=True)},
        tags=["web_analytics"],
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        prompts, count = list_prompts(
            self.team_id, limit=paginator.get_limit(request) or DEFAULT_PAGE_SIZE, offset=paginator.get_offset(request)
        )
        paginator.set_count(count)
        page = self.paginate_queryset(prompts)
        return self.get_paginated_response(AEOPromptSerializer(page, many=True).data)

    @validated_request(
        operation_id="aeo_prompts_retrieve",
        summary="Get an AEO prompt",
        responses={200: OpenApiResponse(response=AEOPromptSerializer)},
        tags=["web_analytics"],
    )
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        try:
            return Response(AEOPromptSerializer(get_prompt(self.team_id, pk)).data)
        except PromptNotFoundError:
            raise NotFound()

    @validated_request(
        request_serializer=AEOPromptUpdateRequestSerializer,
        operation_id="aeo_prompts_partial_update",
        summary="Turn an AEO prompt on or off",
        responses={200: OpenApiResponse(response=AEOPromptSerializer)},
        tags=["web_analytics"],
    )
    def partial_update(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        try:
            prompt = set_prompt_active(self.team_id, pk, request.validated_data["active"])
        except PromptNotFoundError:
            raise NotFound()
        return Response(AEOPromptSerializer(prompt).data)

    @validated_request(
        request_serializer=AEOPromptBulkImportRequestSerializer,
        operation_id="aeo_prompts_bulk_import",
        summary="Import AEO prompts",
        description="Adds prompts to the project's AEO prompt set, or updates the topic and visibility of prompts that already exist. Existing prompts keep their active state.",
        responses={200: OpenApiResponse(response=AEOPromptImportResultSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["post"])
    def bulk_import(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        result = import_prompts(self.team_id, request.validated_data["prompts"])
        return Response(AEOPromptImportResultSerializer(result).data)
