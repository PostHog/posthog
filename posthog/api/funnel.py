from posthog.models import Funnel
from rest_framework import request, serializers, viewsets
from django.db.models import QuerySet
from typing import List, Dict, Any
import json


class FunnelSerializer(serializers.HyperlinkedModelSerializer):
    steps = serializers.SerializerMethodField()

    class Meta:
        model = Funnel
        fields = ['id', 'name', 'deleted', 'steps', 'filters']

    def get_steps(self, funnel: Funnel) -> List[Dict[str, Any]]:
        # for some reason, rest_framework executes SerializerMethodField multiple times,
        # causing lots of slow queries. 
        # Seems a known issue: https://stackoverflow.com/questions/55023511/serializer-being-called-multiple-times-django-python
        if hasattr(funnel, 'steps_cache'):
            return []
        funnel.steps_cache = True # type: ignore

        if self.context['view'].action != 'retrieve' or self.context['request'].GET.get('exclude_count'):
            return []
        return funnel.get_steps()

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Funnel:
        request = self.context['request']
        funnel = Funnel.objects.create(team=request.user.team_set.get(), created_by=request.user, **validated_data)
        return funnel

class FunnelViewSet(viewsets.ModelViewSet):
    queryset = Funnel.objects.all()
    serializer_class = FunnelSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list': # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())
