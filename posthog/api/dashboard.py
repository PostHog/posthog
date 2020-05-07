from rest_framework import request, response, serializers, viewsets
from posthog.models import Dashboard, DashboardItem
from typing import Dict, Any
from django.db.models import QuerySet

class DashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dashboard
        fields = ['id', 'name', 'pinned']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context['request']
        dashboard = Dashboard.objects.create(team=request.user.team_set.get(), **validated_data)
        return dashboard


class DashboardItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardItem
        fields = ['id', 'name', 'filters', 'order', 'type', 'deleted', 'dashboard_id']

    # TODO: validate that dashboard_id is for the same team
    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardItem:
        request = self.context['request']
        dashboard_item = DashboardItem.objects.create(team=request.user.team_set.get(), **validated_data)
        return dashboard_item
 

class DashboardItemsViewSet(viewsets.ModelViewSet):
    queryset = DashboardItem.objects.all()
    serializer_class = DashboardItemSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list':  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('order')


class DashboardsViewSet(viewsets.ModelViewSet):
    queryset = Dashboard.objects.all()
    serializer_class = DashboardSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list':  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('name')
