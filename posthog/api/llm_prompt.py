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
            "deleted",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]

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
    scope_object = "INTERNAL"
    queryset = LLMPrompt.objects.all()
    serializer_class = LLMPromptSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(deleted=False)
