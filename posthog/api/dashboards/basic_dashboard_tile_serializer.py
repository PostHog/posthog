from rest_framework import serializers

from posthog.models import DashboardTile


class BasicDashboardTileSerializer(serializers.ModelSerializer):
    id: serializers.IntegerField = serializers.IntegerField(required=False, read_only=True)
    dashboard: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)
    insight: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True, required=False)
    text: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True, required=False)

    class Meta:
        model = DashboardTile
        fields = "__all__"
