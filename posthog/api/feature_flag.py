from typing import Any, Dict, Optional

from django.db import IntegrityError
from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.user import UserSerializer
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import FeatureFlag
from posthog.permissions import ProjectMembershipNecessaryPermissions


class FeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)
    # :TRICKY: Needed for backwards compatibility
    filters = serializers.DictField(source="get_filters", required=False)
    is_simple_flag = serializers.SerializerMethodField()
    rollout_percentage = serializers.SerializerMethodField()

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "created_by",
            "created_at",
            "is_simple_flag",
            "rollout_percentage",
        ]

    # Simple flags are ones that only have rollout_percentage
    #  That means server side libraries are able to gate these flags without calling to the server
    def get_is_simple_flag(self, feature_flag: FeatureFlag) -> bool:
        return len(feature_flag.groups) == 1 and all(
            len(group.get("properties", [])) == 0 for group in feature_flag.groups
        )

    def get_rollout_percentage(self, feature_flag: FeatureFlag) -> Optional[int]:
        if self.get_is_simple_flag(feature_flag):
            return feature_flag.groups[0].get("rollout_percentage")
        else:
            return None

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        self._update_filters(validated_data)
        try:
            FeatureFlag.objects.filter(key=validated_data["key"], team=request.user.team, deleted=True).delete()
            feature_flag = super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError("This key already exists.", code="key-exists")

        return feature_flag

    def update(self, instance: FeatureFlag, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:  # type: ignore
        try:
            validated_key = validated_data.get("key", None)
            if validated_key:
                FeatureFlag.objects.filter(key=validated_key, team=instance.team, deleted=True).delete()
            self._update_filters(validated_data)
            return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError("This key already exists.", code="key-exists")

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")


class FeatureFlagViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        return queryset.order_by("-created_at")
