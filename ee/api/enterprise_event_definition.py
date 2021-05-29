from rest_framework import serializers

from ee.models.event_definition import EnterpriseEventDefinition


class EnterpriseEventDefinitionSerializer(serializers.ModelSerializer):
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
        read_only_fields = ["id", "name", "owner", "updated_at", "updated_by", "volume_30_day", "query_usage_30_day"]
