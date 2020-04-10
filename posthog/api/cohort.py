from rest_framework import request, response, serializers, viewsets
from posthog.models import Cohort
from typing import Dict, Any
from django.db.models import QuerySet

class CohortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cohort
        fields = ['id', 'name', 'groups', 'deleted']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context['request']
        dashboard_item = Cohort.objects.create(team=request.user.team_set.get(), **validated_data)
        return dashboard_item

class CohortViewSet(viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list':  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('id')
