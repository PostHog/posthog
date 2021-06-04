from rest_framework import serializers

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.shared import UserBasicSerializer
import pdb

class EnterpriseEventDefinitionSerializer(serializers.ModelSerializer):
    owner = UserBasicSerializer
    updated_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = EnterpriseEventDefinition
        fields = (
            "id",
            "name",
            "owner",
            "description",
            "tags",
            "volume_30_day",
            "query_usage_30_day",
            "updated_at",
            "updated_by",
        )
        read_only_fields = ["id", "name", "updated_at", "volume_30_day", "query_usage_30_day"]

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(event_definition, validated_data)
