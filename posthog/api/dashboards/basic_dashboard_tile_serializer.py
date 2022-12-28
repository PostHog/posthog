from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.api.insight import log_insight_activity
from posthog.models import Dashboard, DashboardTile, Insight
from posthog.models.activity_logging.activity_log import Change, model_description


class BasicDashboardTileSerializer(serializers.ModelSerializer):
    id: serializers.IntegerField = serializers.IntegerField(required=False, read_only=True)
    dashboard: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(queryset=Dashboard.objects.all())
    insight: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(
        required=False, queryset=Insight.objects.all()
    )
    # TODO create text cards via this endpoint not dashboards
    text: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True, required=False)

    def validate(self, data):
        team = self.context["team"]
        insight = data.get("insight")
        dashboard = data.get("dashboard")

        if insight.team != team or dashboard.team != team:
            raise ValidationError(detail="Cannot add that insight to that dashboard.")

        if dashboard.deleted:
            raise ValidationError(detail="Cannot add insight to a deleted dashboard.")

        if insight.deleted:
            raise ValidationError(detail="Cannot add deleted insight to a dashboard.")

        if dashboard.get_effective_privilege_level(self.context["user"].id) <= Dashboard.PrivilegeLevel.CAN_VIEW:
            raise PermissionDenied(f"You don't have permission to add insights to dashboard: {dashboard.name}")

        return data

    def create(self, validated_data) -> DashboardTile:
        tiles_before_change = [
            model_description(tile)
            for tile in validated_data.get("insight")
            .dashboard_tiles.exclude(deleted=True)
            .exclude(dashboard__deleted=True)
            .all()
        ]

        tile: DashboardTile
        tile, created = DashboardTile.objects.get_or_create(
            insight=validated_data.get("insight"),
            dashboard=validated_data.get("dashboard"),
            defaults=validated_data,
        )

        if validated_data.get("deleted", None) is not None:
            tile.deleted = validated_data.get("deleted", None)
            tile.save()
        else:
            if tile.deleted:  # then we must be undeleting
                tile.deleted = False
                tile.save()

        tile.insight.refresh_from_db()
        log_insight_activity(
            "updated",
            tile.insight,
            int(tile.insight_id),
            str(tile.insight.short_id),
            self.context["organization_id"],
            self.context["team"].id,
            self.context["user"],
            [
                Change(
                    type="Insight",
                    action="changed",
                    field="dashboards",  # TODO UI is expecting dashboards but should expect dashboard_tiles
                    before=tiles_before_change,
                    after=[
                        model_description(tile)
                        for tile in tile.insight.dashboard_tiles.exclude(deleted=True)
                        .exclude(dashboard__deleted=True)
                        .all()
                    ],
                )
            ],
        )

        return tile

    class Meta:
        model = DashboardTile
        fields = "__all__"
