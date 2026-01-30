import re
from typing import cast

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_team_action, report_user_action
from posthog.models import User
from posthog.models.llm_prompt import LLMPrompt
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle


class LLMPromptSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = LLMPrompt
        fields = [
            "id",
            "name",
            "prompt",
            "version",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", value):
            raise serializers.ValidationError(
                "Only letters, numbers, hyphens (-) and underscores (_) are allowed.",
                code="invalid_name",
            )

        return value

    def validate(self, data):
        team = self.context["get_team"]()
        name = data.get("name")

        # On CREATE: check if name already exists
        if self.instance is None:
            if LLMPrompt.objects.filter(name=name, team=team, deleted=False).exists():
                raise serializers.ValidationError({"name": "A prompt with this name already exists."}, code="unique")

        # On UPDATE: check if name changed OR if restoring a deleted prompt
        else:
            name_to_check = name if name else self.instance.name
            is_being_restored = self.instance.deleted and data.get("deleted") is False
            name_changed = name and self.instance.name != name

            if name_changed or is_being_restored:
                if (
                    LLMPrompt.objects.filter(name=name_to_check, team=team, deleted=False)
                    .exclude(id=self.instance.id)
                    .exists()
                ):
                    raise serializers.ValidationError(
                        {"name": "A prompt with this name already exists."}, code="unique"
                    )

        return data

    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()

        return LLMPrompt.objects.create(
            team=team,
            created_by=request.user,
            **validated_data,
        )


class LLMPromptViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "llm_prompt"
    queryset = LLMPrompt.objects.all()
    serializer_class = LLMPromptSerializer
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "llm-analytics-prompts"

    def safely_get_queryset(self, queryset):
        return queryset.filter(deleted=False)

    def get_throttles(self):
        if self.action == "get_by_name":
            return [BurstRateThrottle(), SustainedRateThrottle()]

        return super().get_throttles()

    def perform_create(self, serializer):
        instance = serializer.save()

        report_user_action(
            cast(User, self.request.user),
            "llma prompt created",
            {
                "prompt_id": str(instance.id),
                "prompt_name": instance.name,
            },
            self.team,
        )

    def perform_update(self, serializer):
        is_being_deleted = serializer.validated_data.get("deleted") is True and not self.get_object().deleted

        instance = serializer.save()

        if is_being_deleted:
            report_user_action(
                cast(User, self.request.user),
                "llma prompt deleted",
                {
                    "prompt_id": str(instance.id),
                    "prompt_name": instance.name,
                },
                self.team,
            )
        else:
            changed_fields = [field for field in serializer.validated_data.keys() if field != "deleted"]

            if changed_fields:
                report_user_action(
                    cast(User, self.request.user),
                    "llma prompt updated",
                    {
                        "prompt_id": str(instance.id),
                        "prompt_name": instance.name,
                        "changed_fields": changed_fields,
                    },
                    self.team,
                )

    @action(
        methods=["GET"],
        detail=False,
        url_path=r"name/(?P<prompt_name>[^/]+)",
        required_scopes=["llm_prompt:read"],
    )
    @monitor(feature=None, endpoint="llma_prompts_get_by_name", method="GET")
    def get_by_name(self, request: Request, prompt_name: str = "", **kwargs) -> Response:
        try:
            prompt = LLMPrompt.objects.get(
                team=self.team,
                name=prompt_name,
                deleted=False,
            )
        except LLMPrompt.DoesNotExist:
            return Response(
                {"detail": f"Prompt with name '{prompt_name}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        report_team_action(
            self.team,
            "llma prompt fetched",
            {
                "prompt_id": str(prompt.id),
                "prompt_name": prompt.name,
            },
        )

        serializer = self.get_serializer(prompt)
        return Response(serializer.data)

    @monitor(feature=None, endpoint="llma_prompts_list", method="GET")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_prompts_retrieve", method="GET")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_prompts_create", method="POST")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_prompts_update", method="PUT")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @monitor(feature=None, endpoint="llma_prompts_partial_update", method="PATCH")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
