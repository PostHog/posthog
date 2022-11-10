from typing import Dict

from rest_framework import authentication, mixins, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import DashboardTemplate, Team


class DashboardTemplateSerializer(serializers.Serializer):
    template_name: serializers.CharField = serializers.CharField(max_length=400)
    source_dashboard: serializers.IntegerField = serializers.IntegerField(allow_null=True)
    dashboard_name: serializers.CharField = serializers.CharField(max_length=400)
    dashboard_description: serializers.CharField = serializers.CharField(max_length=400, allow_blank=True)
    tiles: serializers.JSONField = serializers.JSONField(default=dict)
    tags: serializers.ListField = serializers.ListField(child=serializers.CharField(), allow_null=True)

    def validate(self, data: Dict) -> Dict:
        if not data["template_name"] or str.isspace(data["template_name"]):
            raise serializers.ValidationError("Must provide a template name")

        if not data["source_dashboard"]:
            raise serializers.ValidationError("Must provide the id of the source dashboard")

        if not data["dashboard_name"] or str.isspace(data["dashboard_name"]):
            raise serializers.ValidationError("Must provide a dashboard name")

        if not data.get("tiles") or not isinstance(data["tiles"], list):
            raise serializers.ValidationError("Must provide at least one tile")

        for tile in data["tiles"]:
            if not tile.get("layouts") or not isinstance(tile["layouts"], dict):
                raise serializers.ValidationError("Must provide a tile layouts")

            if not tile.get("type"):
                raise serializers.ValidationError("Must provide a tile type")

            if tile.get("type") == "INSIGHT":
                if not tile.get("filters"):
                    raise serializers.ValidationError("Must provide insight filters")
                if not tile.get("name"):
                    raise serializers.ValidationError("Must provide insight name")
            elif tile.get("type") == "TEXT":
                if not tile.get("body"):
                    raise serializers.ValidationError("Must provide text body")
            else:
                raise serializers.ValidationError("Must provide a valid tile type")

        return data

    def create(self, validated_data: Dict) -> DashboardTemplate:
        team = Team.objects.get(id=self.context["team_id"])
        return DashboardTemplate.objects.create(**validated_data, team=team)


class DashboardTemplatesViewSet(
    StructuredViewSetMixin,
    viewsets.GenericViewSet,
    mixins.CreateModelMixin,
    # mixins.RetrieveModelMixin,
    # mixins.UpdateModelMixin,
    # mixins.DestroyModelMixin,
):
    queryset = DashboardTemplate.objects.all()
    serializer_class = DashboardTemplateSerializer
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(DashboardTemplate.objects.all())
