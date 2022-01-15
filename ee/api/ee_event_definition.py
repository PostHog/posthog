from rest_framework import serializers

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.shared import UserBasicSerializer


class EnterpriseEventDefinitionSerializer(serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)
    verified_by = UserBasicSerializer(read_only=True)

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
            "created_at",
            "updated_at",
            "updated_by",
            "last_seen_at",
            "verified",
            "verified_at",
            "verified_by",
        )
        read_only_fields = [
            "id",
            "name",
            "created_at",
            "updated_at",
            "volume_30_day",
            "query_usage_30_day",
            "last_seen_at",
            "verified_at",
        ]

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        if "verified" in validated_data and validated_data["verified"]:
            validated_data["verified_by"] = self.context["request"].user
        else:
            validated_data["verified_by"] = None
        return super().update(event_definition, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = UserBasicSerializer(instance=instance.owner).data
        return representation
