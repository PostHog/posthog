import re

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.llm_prompt import LLMPrompt
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
        existing_prompt = self.instance

        # On CREATE: check if name already exists
        if self.context["request"].method == "POST":
            if LLMPrompt.objects.filter(name=name, team=team, deleted=False).exists():
                raise serializers.ValidationError({"name": "A prompt with this name already exists."}, code="unique")

        # On UPDATE: check if name changed OR if restoring a deleted prompt
        if existing_prompt:
            name_to_check = name if name else existing_prompt.name
            is_being_restored = existing_prompt.deleted and data.get("deleted") is False
            name_changed = name and existing_prompt.name != name

            if name_changed or is_being_restored:
                if (
                    LLMPrompt.objects.filter(name=name_to_check, team=team, deleted=False)
                    .exclude(id=existing_prompt.id)
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

    def safely_get_queryset(self, queryset):
        return queryset.filter(deleted=False)

    def get_throttles(self):
        if self.action == "get_by_name":
            return [BurstRateThrottle(), SustainedRateThrottle()]

        return super().get_throttles()

    @action(
        methods=["GET"],
        detail=False,
        url_path=r"name/(?P<prompt_name>[^/]+)",
        required_scopes=["llm_prompt:read"],
    )
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

        serializer = self.get_serializer(prompt)
        return Response(serializer.data)
