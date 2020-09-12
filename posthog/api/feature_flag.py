from typing import Any, Dict

import posthoganalytics
from django.db import IntegrityError
from django.db.models import QuerySet
from rest_framework import response, serializers, status, viewsets

from posthog.api.user import UserSerializer
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import FeatureFlag


class FeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "name",
            "key",
            "rollout_percentage",
            "filters",
            "deleted",
            "active",
            "created_by",
            "created_at",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team"] = request.user.team_set.get()
        try:
            feature_flag = super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("key-exists")

        return feature_flag

    def update(self, instance: FeatureFlag, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:  # type: ignore
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError("key-exists")


class FeatureFlagViewSet(AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset.filter(team=self.request.user.team_set.get()).order_by("-created_at",)
