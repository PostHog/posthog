from django.utils import timezone
from rest_framework import exceptions, serializers

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
        now = timezone.now()

        if "verified" in validated_data and validated_data["verified"] and not event_definition.verified:
            # Verify event only if previously unverified
            validated_data["verified_by"] = self.context["request"].user
            validated_data["verified_at"] = now
            validated_data["verified"] = True

        elif "verified" in validated_data and not validated_data["verified"]:
            # Unverifying event nullifies verified properties
            validated_data["verified_by"] = None
            validated_data["verified_at"] = None
            validated_data["verified"] = False
        else:
            # Don't allow editing verified properties in any other situation
            validated_data.pop("verified_by", None)
            validated_data.pop("verified_at", None)
            validated_data.pop("verified", None)

        return super().update(event_definition, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = UserBasicSerializer(instance=instance.owner).data if instance.owner else None
        representation["updated_by"] = (
            UserBasicSerializer(instance=instance.updated_by).data if instance.updated_by else None
        )
        representation["verified_by"] = (
            UserBasicSerializer(instance=instance.verified_by).data if instance.verified_by else None
        )
        return representation
