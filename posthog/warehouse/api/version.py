from rest_framework import serializers
from posthog.warehouse.models.version_control import Version
from posthog.api.shared import UserBasicSerializer


class VersionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Version
        fields = ["id", "created_by", "created_at", "content_hash"]
