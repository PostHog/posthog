from typing import Any, Dict

from django.db.models import QuerySet
from rest_framework import request, serializers, viewsets

from posthog.models import Plugin


class PluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plugin
        fields = [
            "id",
            "name",
            "url",
            "enabled",
            "order",
            "config",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:
        request = self.context["request"]
        plugin = Plugin.objects.create(team=request.user.team, **validated_data)
        return plugin

    def update(self, plugin: Plugin, validated_data: Dict, *args: Any, **kwargs: Any) -> Plugin:  # type: ignore
        plugin.name = validated_data.get("name", plugin.name)
        plugin.url = validated_data.get("url", plugin.url)
        plugin.enabled = validated_data.get("enabled", plugin.enabled)
        plugin.config = validated_data.get("config", plugin.config)
        plugin.order = validated_data.get("order", plugin.order)
        plugin.save()
        return plugin


class PluginViewSet(viewsets.ModelViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        return queryset.filter(team=self.request.user.team).order_by("order")
