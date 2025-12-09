from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.llm_prompt import LLMPrompt


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
        ]
        read_only_fields = [
            "id",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()

        return LLMPrompt.objects.create(
            team=team,
            created_by=request.user,
            **validated_data,
        )


class LLMPromptViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = LLMPrompt.objects.all()
    serializer_class = LLMPromptSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(deleted=False)
