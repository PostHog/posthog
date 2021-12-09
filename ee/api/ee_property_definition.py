from rest_framework import serializers

from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.api.shared import UserBasicSerializer


class EnterprisePropertyDefinitionSerializer(serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = EnterprisePropertyDefinition
        fields = (
            "id",
            "name",
            "description",
            "tags",
            "is_numerical",
            "updated_at",
            "updated_by",
            "query_usage_30_day",
        )
        read_only_fields = ["id", "name", "is_numerical", "query_usage_30_day"]

    def update(self, event_definition: EnterprisePropertyDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(event_definition, validated_data)
