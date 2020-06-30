from posthog.models import DashboardItem
from django.db.models import QuerySet
from posthog.models import Annotation
from rest_framework import request, serializers, viewsets
from typing import Dict, Any
from posthog.api.user import UserSerializer

class AnnotationSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)

    class Meta:
        model = Annotation
        fields = ['id', 'content', 'date_marker', 'creation_type', 'dashboard_item', 'created_by', 'created_at', 'updated_at', 'deleted']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Annotation:
        request = self.context['request']
        print(validated_data)
        annotation = Annotation.objects.create(team=request.user.team_set.get(), created_by=request.user, **validated_data)
        return annotation

class AnnotationsViewSet(viewsets.ModelViewSet):
    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        team = self.request.user.team_set.get()
        if self.action == 'list':  # type: ignore
            queryset = self._filter_request(self.request, queryset)
            queryset = queryset.filter(deleted =False)

        return queryset\
            .filter(team=team)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        for key, _ in request.GET.items():
            if key == 'after':
                queryset = queryset.filter(created_at__gt=request.GET['after'])
            elif key == 'before':
                queryset = queryset.filter(created_at__lt=request.GET['before'])
            elif key == 'dashboardItemId':
                queryset = queryset.filter(dashboard_item_id=request.GET['dashboardItemId'])
        return queryset