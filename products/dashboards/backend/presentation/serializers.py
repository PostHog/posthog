from rest_framework import serializers


# The tile shape an insight payload carries for each dashboard it sits on. No docstring: it would
# land in the generated OpenAPI component as a description.
class DashboardTileBasicSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="ID of the dashboard tile.")
    dashboard_id = serializers.IntegerField(read_only=True, help_text="ID of the dashboard the tile sits on.")
    deleted = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether the tile was removed from the dashboard.",
    )
