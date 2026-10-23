import math
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
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

from products.aeo.backend.facade.api import (
    get_prompt,
    import_prompts,
    list_prompt_topics,
    list_prompts,
    set_prompt_active,
)
from products.aeo.backend.facade.contracts import (
    AEO_CITATION_TRACKING_FLAG,
    PROMPT_TOPIC_MAX_LENGTH,
    Prompt,
    PromptEngineCheck,
    PromptImport,
    PromptImportResult,
    PromptNotFoundError,
    PromptTopic,
)

MAX_PROMPTS_PER_IMPORT = 2000
DEFAULT_PAGE_SIZE = 100
# Bounds the request body. Prompts longer than the engines accept are counted as skipped, not rejected.
MAX_IMPORTED_PROMPT_CHARS = 10_000

EXTERNAL_VISIBILITY_HELP = (
    "Share of answers (0-100) that mention the brand for this prompt, as reported by the tool the prompt set "
    "came from. Kept to benchmark against our own citation rate."
)


class AEOPromptEngineCheckSerializer(DataclassSerializer):
    class Meta:
        dataclass = PromptEngineCheck
        ref_name = "AEOPromptEngineCheck"
        extra_kwargs = {
            "engine": {
                "help_text": "Answer engine that ran the prompt, for example 'claude-web-search', 'openai-web-search' or 'exa-answer'."
            },
            "cited": {"help_text": "Whether the answer cited a URL on one of the target domains."},
            "check_failed": {
                "help_text": "The engine did not answer. When true, 'cited' is false and says nothing about citations."
            },
            "checked_at": {"help_text": "When the check ran."},
        }


class AEOPromptSerializer(DataclassSerializer):
    latest_checks = AEOPromptEngineCheckSerializer(
        many=True,
        help_text="The most recent check for each answer engine that ran the prompt. Empty when the prompt never ran.",
    )

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


class AEOPromptListQuerySerializer(serializers.Serializer):
    topic = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=PROMPT_TOPIC_MAX_LENGTH,
        help_text="Only list prompts with this topic. An empty value lists the prompts that have no topic.",
    )
    # A QueryDict reads a missing boolean as false, so the default keeps "no filter" distinct from active=false.
    active = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Only list prompts that are on (true) or off (false). Omit to list both.",
    )


class AEOPromptTopicSerializer(DataclassSerializer):
    class Meta:
        dataclass = PromptTopic
        ref_name = "AEOPromptTopic"
        extra_kwargs = {
            "topic": {"help_text": "Topic name. Empty for prompts that have no topic."},
            "prompts": {"help_text": "How many prompts in the set have this topic."},
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
    scope_object_read_actions = ["list", "retrieve", "topics"]
    scope_object_write_actions = ["partial_update", "bulk_import"]
    pagination_class = PrecountedLimitOffsetPagination

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        distinct_id = getattr(request.user, "distinct_id", None)
        if not distinct_id or not posthog_feature_flag_enabled(
            AEO_CITATION_TRACKING_FLAG, distinct_id, organization_id=self.organization_id
        ):
            raise PermissionDenied("This feature is not available.")

    @validated_request(
        query_serializer=AEOPromptListQuerySerializer,
        operation_id="aeo_prompts_list",
        summary="List AEO prompts",
        description="Lists the project's AEO prompt set, ordered by topic and then rank, one page at a time. Filter by topic or by on/off state. Each prompt carries its latest check per answer engine.",
        responses={200: AEOPromptSerializer(many=True)},
        tags=["web_analytics"],
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        prompts, count = list_prompts(
            self.team_id,
            limit=paginator.get_limit(request) or DEFAULT_PAGE_SIZE,
            offset=paginator.get_offset(request),
            topic=request.validated_query_data.get("topic"),
            active=request.validated_query_data.get("active"),
        )
        paginator.set_count(count)
        page = self.paginate_queryset(prompts)
        return self.get_paginated_response(AEOPromptSerializer(page, many=True).data)

    @validated_request(
        operation_id="aeo_prompts_retrieve",
        summary="Get an AEO prompt",
        description="Gets one prompt from the project's AEO prompt set, with its latest check per answer engine.",
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
        description="Turns a prompt on or off. Only active prompts run against the answer engines. Past checks are kept either way.",
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
        operation_id="aeo_prompts_topics",
        summary="List AEO prompt topics",
        description="Lists the topics in the project's AEO prompt set, with the number of prompts in each.",
        responses={200: OpenApiResponse(response=AEOPromptTopicSerializer(many=True))},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def topics(self, request: Request, **kwargs: Any) -> Response:
        return Response(AEOPromptTopicSerializer(list_prompt_topics(self.team_id), many=True).data)

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
