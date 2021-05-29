from rest_framework import serializers

from ee.models.property_definition import EnterprisePropertyDefinition


class EnterprisePropertyDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnterprisePropertyDefinition
        fields = (
            "id",
            "name",
            "description",
            "tags",
            "volume_30_day",
            "query_usage_30_day",
        )
        read_only_fields = ["id", "name", "volume_30_day", "query_usage_30_day"]
