from rest_framework import serializers

from products.dashboards.backend.models.dashboard_tile import DashboardTile


# The tile shape an insight payload carries for each dashboard it sits on. No docstring: it would
# land in the generated OpenAPI component as a description.
class DashboardTileBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardTile
        fields = ["id", "dashboard_id", "deleted"]
        extra_kwargs = {
            "id": {"help_text": "ID of the dashboard tile."},
            "dashboard_id": {"help_text": "ID of the dashboard the tile sits on."},
            "deleted": {"help_text": "Whether the tile was removed from the dashboard."},
        }
