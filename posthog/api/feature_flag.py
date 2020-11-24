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
    is_simple_flag = serializers.SerializerMethodField()

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
            "is_simple_flag",
        ]

    # Simple flags are ones that only have rollout_percentage
    #  That means server side libraries are able to gate these flags without calling to the server
    def get_is_simple_flag(self, feature_flag: FeatureFlag):
        filters = feature_flag.filters
        if not filters:
            return True
        if not filters.get("properties", []):
            return True
        return False

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team"] = request.user.team
        try:
            feature_flag = super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("This key already exists.", code="key-exists")

        return feature_flag

    def update(self, instance: FeatureFlag, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:  # type: ignore
        try:
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError("This key already exists.", code="key-exists")


class FeatureFlagViewSet(AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":  # type: ignore
            queryset = queryset.filter(deleted=False)
        return queryset.filter(team=self.request.user.team).order_by("-created_at")
