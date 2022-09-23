from typing import Any, Dict, List

from django.utils.timezone import now
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Dashboard, DashboardTile, Text


class DashboardTileListSerializer(serializers.ListSerializer):
    """see https://www.django-rest-framework.org/api-guide/serializers/#customizing-multiple-update"""

    def update(self, instance: List[DashboardTile], validated_data: List[Dict]) -> List[DashboardTile]:
        if not isinstance(self.parent.instance, Dashboard):
            raise ValidationError("Text tiles must be updated on a dashboard")
        else:
            parent_dashboard: Dashboard = self.parent.instance

        serializer = DashboardTileSerializer(context=self.context)

        tile_mapping: Dict[int, DashboardTile] = {tile.id: tile for tile in instance}
        data_mapping = {item["id"]: item for item in validated_data if item.get("id", None)}
        new_text_tiles = [item for item in validated_data if "id" not in item]

        updated_tiles = []
        for tile_id, data in data_mapping.items():
            tile = tile_mapping.get(tile_id, None)
            if tile is not None:
                data["text"]["team"] = parent_dashboard.team_id
                data["dashboard"] = parent_dashboard.id
                updated_tiles.append(serializer.update(instance=tile, validated_data=data))

        for new_tile in new_text_tiles:
            new_tile["team_id"] = parent_dashboard.team_id
            new_tile["dashboard"] = parent_dashboard.id
            updated_tiles.append(serializer.create(new_tile))

        # Perform deletions.
        for tile_id, tile in tile_mapping.items():
            if tile_id not in data_mapping:
                tile.delete()

        return updated_tiles


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
        list_serializer_class = DashboardTileListSerializer
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

    def update(self, instance: DashboardTile, validated_data: Dict, **kwargs) -> DashboardTile:
        if "insight" in validated_data:
            # insight is readonly from tile context
            validated_data.pop("insight")
        elif "text" in validated_data:
            # this must be a text tile
            assert instance.text is not None
            instance.text.last_modified_at = now()
            instance.text.last_modified_by = self.context["request"].user

        updated_tile = super().update(instance, validated_data)

        return updated_tile


class DashboardTilesViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    queryset = DashboardTile.objects.select_related("dashboard", "insight", "text")
    filter_rewrite_rules = {"team_id": "dashboard__team_id"}
    serializer_class = DashboardTileSerializer

    def get_serializer(self, *args, **kwargs):
        if isinstance(kwargs.get("data", {}), list):
            kwargs["many"] = True

        return super(DashboardTilesViewSet, self).get_serializer(*args, **kwargs)

    def update(self, request, *args, **kwargs):
        breakpoint()
        pass

    def create(self, request, *args, **kwargs):
        if isinstance(request.data, List):
            datum: Dict
            for datum in request.data:
                datum["dashboard"] = kwargs["parent_lookup_dashboard_id"]
                datum["text"]["team"] = self.team.id
        else:
            request.data["text"]["team"] = self.team.id
            request.data["dashboard"] = kwargs["parent_lookup_dashboard_id"]

        return super().create(request, *args, **kwargs)
