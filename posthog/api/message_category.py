from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import MessageCategory


class MessageCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageCategory
        fields = (
            "id",
            "key",
            "name",
            "description",
            "public_description",
            "category_type",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
            "created_by",
        )

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class MessageCategoryViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    serializer_class = MessageCategorySerializer
    queryset = MessageCategory.objects.all()

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(
                team_id=self.team_id,
                deleted=False,
            )
            .select_related("created_by")
            .order_by("-created_at")
        )
