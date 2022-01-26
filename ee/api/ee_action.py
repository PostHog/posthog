from rest_framework import serializers

from ee.models.action import EnterpriseAction
from posthog.api.shared import UserBasicSerializer


class EnterpriseActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnterpriseAction
        fields = (
            "id",
            "name",
            "owner",
            "description",
            "tags",
            "post_to_slack",
            "slack_message_format",
            "steps",
            "created_at",
            "created_by",
            "deleted",
            "is_calculating",
            "last_calculated_at",
            "team_id",
        )

        read_only_fields = [
            "id",
            "created_at",
            "last_calculated_at",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["owner"] = UserBasicSerializer(instance=instance.owner).data if instance.owner else None
        return representation
