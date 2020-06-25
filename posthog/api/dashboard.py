from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from posthog.models import Dashboard, DashboardItem
from typing import Dict, Any
from django.db.models import QuerySet
from datetime import datetime

class DashboardSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()  # type: ignore
    class Meta:
        model = Dashboard
        fields = ['id', 'name', 'pinned', 'items', 'created_at', 'created_by']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Dashboard:
        request = self.context['request']
        validated_data['created_by'] = request.user
        team = request.user.team_set.get()
        dashboard = Dashboard.objects.create(team=team, **validated_data)

        if request.data.get('items'):
            for item in request.data['items']:
                DashboardItem.objects.create(
                    **{key: value for key, value in item.items() if key not in ('id', 'deleted', 'dashboard', 'team')},
                    dashboard=dashboard,
                    team=team,
                )

        return dashboard

    def get_items(self, dashboard: Dashboard):
        if self.context['view'].action == 'list':
            return None
        items = dashboard.items.filter(deleted=False).order_by('order').all()
        return DashboardItemSerializer(items, many=True).data


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


class DashboardItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardItem
        fields = ['id', 'name', 'filters', 'order', 'type', 'deleted', 'dashboard', 'layouts', 'color', 'last_refresh', 'refreshing']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardItem:
        request = self.context['request']
        team = request.user.team_set.get()
        if validated_data['dashboard'].team == team:
            dashboard_item = DashboardItem.objects.create(team=team, last_refresh=datetime.now(), **validated_data)
            return dashboard_item
        else:
            raise serializers.ValidationError("Dashboard not found")


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

    @action(methods=['patch'], detail=False)
    def layouts(self, request):
        team = request.user.team_set.get()

        for data in request.data['items']:
            self.queryset.filter(team=team, pk=data['id']).update(layouts=data['layouts'])

        serializer = self.get_serializer(self.queryset, many=True)
        return response.Response(serializer.data)
