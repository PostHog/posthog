from rest_framework import serializers
from posthog.warehouse.models import ExternalDataSchema


class ExternalDataSchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSchema

        fields = ["id", "name", "table", "should_sync", "latest_error"]
