from posthog.models import FeatureFlag
from posthog.api.user import UserSerializer
from rest_framework import request, serializers, viewsets
from django.db.models import QuerySet
from typing import List, Dict, Any
import json

class FeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)

    class Meta:
        model = FeatureFlag
        fields = ['id', 'name', 'key', 'rollout_percentage', 'filters', 'deleted', 'active', 'created_by', 'created_at']

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context['request']
        validated_data['created_by'] = request.user
        feature_flag = FeatureFlag.objects.create(team=request.user.team_set.get(), **validated_data)
        return feature_flag

class FeatureFlagViewSet(viewsets.ModelViewSet):
    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == 'list': # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset\
            .filter(team=self.request.user.team_set.get())\
            .order_by('-created_at')
