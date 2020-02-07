from rest_framework import request, response, serializers, viewsets # type: ignore
from posthog.models import DashboardItem
from typing import Dict, Any
from django.db.models import QuerySet

class DashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardItem
        fields = ['id', 'name', 'filters', 'order', 'type', 'deleted']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> DashboardItem:
        request = self.context['request']
        dashboard_item = DashboardItem.objects.create(team=request.user.team_set.get(), **validated_data)
        return dashboard_item
 

class DashboardViewSet(viewsets.ModelViewSet):
    queryset = DashboardItem.objects.all()
    serializer_class = DashboardSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list':
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('order')
