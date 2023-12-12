from rest_framework import serializers
from posthog.warehouse.models import ExternalDataSchema
from typing import Optional


class ExternalDataSchemaSerializer(serializers.ModelSerializer):
    table = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ExternalDataSchema

        fields = ["id", "name", "table", "should_sync", "latest_error"]

    def get_table(self, schema: ExternalDataSchema) -> Optional[dict]:
        from posthog.warehouse.api.table import SimpleTableSerializer

        return SimpleTableSerializer(schema.table).data or None
