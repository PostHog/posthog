from rest_framework import serializers, viewsets
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.hog_functions.hog_function_group import HogFunctionGroup

class HogFunctionGroupSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = HogFunctionGroup
        fields = ["id", "name", "created_at", "created_by", "updated_at"]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def create(self, validated_data):
        validated_data["team"] = self.context["get_team"]()
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)

class HogFunctionGroupViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "hog_function"
    queryset = HogFunctionGroup.objects.all()
    serializer_class = HogFunctionGroupSerializer
