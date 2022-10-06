from typing import Any, Dict

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.models import DashboardTile, Text


class TextSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Text
        fields = "__all__"
        read_only_fields = ["id", "created_by", "last_modified_by", "last_modified_at"]


class DashboardTileSerializer(serializers.ModelSerializer):
    id: serializers.IntegerField = serializers.IntegerField(required=False)
    text = TextSerializer(required=False)

    class Meta:
        model = DashboardTile
        fields = "__all__"
        read_only_fields = ["id", "insight"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardTile:
        if "text" in validated_data:
            text = validated_data.pop("text")
            user = self.context["request"].user
            text["created_by"] = user
            instance = DashboardTile.objects.create(**validated_data, text=Text.objects.create(**text))
        else:
            instance = DashboardTile.objects.create(**validated_data)
        return instance


#
#
# class DashboardTilesViewSet(
#     StructuredViewSetMixin,
#     mixins.CreateModelMixin,
#     viewsets.GenericViewSet,
# ):
#     queryset = DashboardTile.objects.select_related("dashboard", "insight", "text")
#     filter_rewrite_rules = {"team_id": "dashboard__team_id"}
#     serializer_class = DashboardTileSerializer
#
#     def create(self, request, *args, **kwargs):
#         request.data["text"]["team"] = self.team.id
#         request.data["dashboard"] = kwargs["parent_lookup_dashboard_id"]
#
#         dashboard = Dashboard.objects.get(pk=kwargs["parent_lookup_dashboard_id"])
#         context = super(DashboardTilesViewSet, self).get_serializer_context()
#         breakpoint()
#         dashboard_serializer = DashboardSerializer(dashboard, context)
#         dashboard_serializer.is_valid(raise_exception=True)
#         return Response(dashboard_serializer.data)
