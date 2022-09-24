import datetime
from typing import Any, Dict, List

from django.utils.timezone import now
from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
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

    def update(self, instance: DashboardTile, validated_data: Dict, **kwargs) -> DashboardTile:
        if "insight" in validated_data:
            # insight is readonly from tile context
            validated_data.pop("insight")
        elif "text" in validated_data:
            # this must be a text tile
            text = validated_data.pop("text")
            assert text is not None
            assert self.initial_data["text"] is not None
            text.last_modified_at = now()
            # id isn't included in validated data because it's read-only
            text_id = self.initial_data["text"]["id"]
            if text_id:
                text["last_modified_by"] = self.context["request"].user
                text["last_modified_at"] = datetime.datetime.now()
                updated_text, created = Text.objects.update_or_create(
                    id=text_id,
                    defaults=text,
                )
            else:
                text["created_by"] = self.context["request"].user
                updated_text = Text.objects.create(**text)
            instance.text = updated_text
        updated_tile = super().update(instance, validated_data)

        return updated_tile


class DashboardTilesViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = DashboardTile.objects.select_related("dashboard", "insight", "text")
    filter_rewrite_rules = {"team_id": "dashboard__team_id"}
    serializer_class = DashboardTileSerializer

    def get_serializer(self, *args, **kwargs):
        if isinstance(kwargs.get("data", {}), list):
            kwargs["many"] = True

        return super(DashboardTilesViewSet, self).get_serializer(*args, **kwargs)

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
