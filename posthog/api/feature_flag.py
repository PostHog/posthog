from typing import Any, Dict, Optional, cast

import posthoganalytics
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from rest_framework import authentication, exceptions, request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import FeatureFlag, feature_flag
from posthog.models.feature_flag import FeatureFlagOverride, get_active_feature_flags
from posthog.permissions import ProjectMembershipNecessaryPermissions


class FeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
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

    def validate_key(self, value):
        exclude_kwargs = {}
        if self.instance:
            exclude_kwargs = {"pk": cast(FeatureFlag, self.instance).pk}

        if (
            FeatureFlag.objects.filter(key=value, team=self.context["request"].user.team, deleted=False)
            .exclude(**exclude_kwargs)
            .exists()
        ):
            raise serializers.ValidationError("There is already a feature flag with this key.", code="unique")

        return value

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        self._update_filters(validated_data)

        variants = validated_data.get("filters", {}).get("multivariate", {}).get("variants", [])
        variant_rollout_sum = 0
        for variant in variants:
            variant_rollout_sum += variant.get("rollout_percentage")

        if len(variants) > 0 and variant_rollout_sum != 100:
            raise exceptions.ValidationError(
                "Invalid variant definitions: Variant rollout percentages must sum to 100."
            )

        FeatureFlag.objects.filter(key=validated_data["key"], team=request.user.team, deleted=True).delete()
        instance = super().create(validated_data)

        posthoganalytics.capture(
            request.user.distinct_id, "feature flag created", instance.get_analytics_metadata(),
        )

        return instance

    def update(self, instance: FeatureFlag, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_key = validated_data.get("key", None)
        if validated_key:
            FeatureFlag.objects.filter(key=validated_key, team=instance.team, deleted=True).delete()
        self._update_filters(validated_data)
        instance = super().update(instance, validated_data)

        posthoganalytics.capture(
            request.user.distinct_id, "feature flag updated", instance.get_analytics_metadata(),
        )
        return instance

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")


class FeatureFlagViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    legacy_team_compatibility = True  # to be moved to a separate Legacy*ViewSet Class

    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        TemporaryTokenAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        return queryset.order_by("-created_at")

    @action(methods=["GET"], detail=False)
    def my_flags(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy, since 'AnonymousUser' has no 'feature_flag_override'
            raise serializers.ValidationError("Must be authenticated to get feature flags.")
        flags = get_active_feature_flags(self.team, request.user.distinct_id)
        return Response({"distinct_id": request.user.distinct_id, "flags": flags})


class FeatureFlagOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlagOverride
        fields = [
            "id",
            "feature_flag",
            "user",
            "override_value",
        ]

    _analytics_updated_event_name = "feature flag override updated"
    _analytics_created_event_name = "feature flag override created"

    def validate_override_value(self, value):
        if not isinstance(value, str) and not isinstance(value, bool):
            raise serializers.ValidationError(
                f"Overridden feature flag value ('{value}') must be a string or a boolean.", code="invalid_feature_flag"
            )
        return value

    def create(self, validated_data: Dict) -> FeatureFlagOverride:
        feature_flag_override, created = FeatureFlagOverride.objects.update_or_create(
            feature_flag=validated_data["feature_flag"],
            user=validated_data["user"],
            defaults={"override_value": validated_data["override_value"]},
        )
        request = self.context["request"]
        if created:
            posthoganalytics.capture(
                request.user.distinct_id, self._analytics_created_event_name,
            )
        else:
            posthoganalytics.capture(
                request.user.distinct_id, self._analytics_updated_event_name,
            )
        return feature_flag_override

    def update(self, instance: FeatureFlagOverride, validated_data: Dict) -> FeatureFlagOverride:
        request = self.context["request"]
        posthoganalytics.capture(
            request.user.distinct_id, self._analytics_updated_event_name,
        )
        return super().update(instance, validated_data)


class FeatureFlagOverrideViewset(
    AnalyticsDestroyModelMixin, viewsets.ModelViewSet,
):
    queryset = FeatureFlagOverride.objects.all()
    serializer_class = FeatureFlagOverrideSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        TemporaryTokenAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self) -> QuerySet:
        if not self.request.user.is_authenticated:  # for mypy, since 'AnonymousUser' has no 'team'
            raise exceptions.NotAuthenticated
        queryset = (
            super()
            .get_queryset()
            .filter(feature_flag__team=self.request.user.team, user__current_team=self.request.user.team)
        )
        if self.action == "list":
            feature_flag_id = self.request.GET.get("feature_flag_id")
            if feature_flag_id:
                queryset = queryset.filter(feature_flag_id=feature_flag_id)
        return queryset

    def perform_create(self, serializer):
        self._check_team_permissions(serializer)
        return super().perform_create(serializer)

    def perform_update(self, serializer):
        self._check_team_permissions(serializer)
        return super().perform_update(serializer)

    def _check_team_permissions(self, serializer: FeatureFlagOverrideSerializer):
        if not self.request.user.is_authenticated:  # for mypy, since 'AnonymousUser' has no 'team'
            raise exceptions.NotAuthenticated

        feature_flag = serializer.validated_data.get("feature_flag")
        user = serializer.validated_data.get("user")

        if serializer.instance:
            exisiting_feature_flag_override = cast(FeatureFlagOverride, serializer.instance)
            if not feature_flag and exisiting_feature_flag_override:
                feature_flag = exisiting_feature_flag_override.feature_flag
            if not user and exisiting_feature_flag_override:
                user = exisiting_feature_flag_override.user

        if feature_flag.team != self.request.user.team or user.team != self.request.user.team:
            raise PermissionDenied

    @action(methods=["GET", "POST"], detail=False)
    def my_overrides(self, request: request.Request, **kwargs):
        if request.method == "GET":
            feature_flag_overrides = super().get_queryset().filter(user=request.user)
            override_dict = {}
            for feature_flag_override in feature_flag_overrides:
                key = feature_flag_override.feature_flag.key
                value = feature_flag_override.override_value
                override_dict[key] = value
            return Response({"feature_flag_overrides": override_dict})
        if request.method == "POST":
            user = request.user
            serializer = FeatureFlagOverrideSerializer(
                data={**request.data, "user": user.id}, context={"request": request}
            )
            if serializer.is_valid(raise_exception=True):
                self._check_team_permissions(serializer)
            super().perform_create(serializer)
            return Response({serializer.instance.feature_flag.key: serializer.instance.override_value})
