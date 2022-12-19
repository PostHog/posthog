from django.utils import timezone
from rest_framework import serializers

from ee.models.event_definition import EnterpriseEventDefinition
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin


class EnterpriseEventDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)
    verified_by = UserBasicSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    is_action = serializers.SerializerMethodField(read_only=True)
    action_id = serializers.IntegerField(read_only=True)
    is_calculating = serializers.BooleanField(read_only=True)
    last_calculated_at = serializers.DateTimeField(read_only=True)
    last_updated_at = serializers.DateTimeField(read_only=True)
    post_to_slack = serializers.BooleanField(default=False)

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
            "last_updated_at",
            "verified",
            "verified_at",
            "verified_by",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
            "post_to_slack",
        )
        read_only_fields = [
            "id",
            "name",
            "created_at",
            "updated_at",
            "volume_30_day",
            "query_usage_30_day",
            "last_seen_at",
            "last_updated_at",
            "verified_at",
            "verified_by",
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
        ]

    def update(self, event_definition: EnterpriseEventDefinition, validated_data):
        validated_data["updated_by"] = self.context["request"].user

        if "verified" in validated_data:
            if validated_data["verified"] and not event_definition.verified:
                # Verify event only if previously unverified
                validated_data["verified_by"] = self.context["request"].user
                validated_data["verified_at"] = timezone.now()
                validated_data["verified"] = True
            elif not validated_data["verified"]:
                # Unverifying event nullifies verified properties
                validated_data["verified_by"] = None
                validated_data["verified_at"] = None
                validated_data["verified"] = False
            else:
                # Attempting to re-verify an already verified event, invalid action. Ignore attribute.
                validated_data.pop("verified")

        return super().update(event_definition, validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = (
            UserBasicSerializer(instance=instance.owner).data if hasattr(instance, "owner") and instance.owner else None
        )
        return representation

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None
