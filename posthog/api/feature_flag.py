import json
from typing import Any, Dict, Optional, cast

from django.db.models import Prefetch, QuerySet
from rest_framework import authentication, exceptions, request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.event_usage import report_user_action
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import FeatureFlag
from posthog.models.feature_flag import FeatureFlagOverride
from posthog.models.property import Property
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


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
        no_properties_used = all(len(condition.get("properties", [])) == 0 for condition in feature_flag.conditions)
        return (
            len(feature_flag.conditions) == 1
            and no_properties_used
            and feature_flag.aggregation_group_type_index is None
        )

    def get_rollout_percentage(self, feature_flag: FeatureFlag) -> Optional[int]:
        if self.get_is_simple_flag(feature_flag):
            return feature_flag.conditions[0].get("rollout_percentage")
        else:
            return None

    def validate_key(self, value):
        exclude_kwargs = {}
        if self.instance:
            exclude_kwargs = {"pk": cast(FeatureFlag, self.instance).pk}

        if (
            FeatureFlag.objects.filter(key=value, team_id=self.context["team_id"], deleted=False)
            .exclude(**exclude_kwargs)
            .exists()
        ):
            raise serializers.ValidationError("There is already a feature flag with this key.", code="unique")

        return value

    def validate_filters(self, filters):
        aggregation_group_type_index = filters.get("aggregation_group_type_index", None)

        def properties_all_match(predicate):
            return all(
                predicate(Property(**property))
                for condition in filters["groups"]
                for property in condition.get("properties", [])
            )

        if aggregation_group_type_index is None:
            is_valid = properties_all_match(lambda prop: prop.type in ["person", "cohort"])
            if not is_valid:
                raise serializers.ValidationError("Filters are not valid (can only use person and cohort properties)")
        else:
            is_valid = properties_all_match(
                lambda prop: prop.type == "group" and prop.group_type_index == aggregation_group_type_index
            )
            if not is_valid:
                raise serializers.ValidationError("Filters are not valid (can only use group properties)")

        return filters

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        self._update_filters(validated_data)

        variants = (validated_data.get("filters", {}).get("multivariate", {}) or {}).get("variants", [])
        variant_rollout_sum = 0
        for variant in variants:
            variant_rollout_sum += variant.get("rollout_percentage")

        if len(variants) > 0 and variant_rollout_sum != 100:
            raise exceptions.ValidationError(
                "Invalid variant definitions: Variant rollout percentages must sum to 100."
            )

        FeatureFlag.objects.filter(key=validated_data["key"], team=self.context["team_id"], deleted=True).delete()
        instance = super().create(validated_data)

        report_user_action(
            request.user, "feature flag created", instance.get_analytics_metadata(),
        )

        return instance

    def update(self, instance: FeatureFlag, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_key = validated_data.get("key", None)
        if validated_key:
            FeatureFlag.objects.filter(key=validated_key, team=instance.team, deleted=True).delete()
        self._update_filters(validated_data)
        instance = super().update(instance, validated_data)

        report_user_action(
            request.user, "feature flag updated", instance.get_analytics_metadata(),
        )
        return instance

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")


class FeatureFlagViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.
    """

    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        TemporaryTokenAuthentication,  # Allows endpoint to be called from the Toolbar
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.filter(deleted=False, experiment__isnull=True)
        return queryset.order_by("-created_at")

    @action(methods=["GET"], detail=False)
    def my_flags(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        feature_flags = (
            FeatureFlag.objects.filter(team=self.team, active=True, deleted=False)
            .prefetch_related(
                Prefetch(
                    "featureflagoverride_set",
                    queryset=FeatureFlagOverride.objects.filter(user=request.user),
                    to_attr="my_overrides",
                )
            )
            .order_by("-created_at")
        )
        groups = json.loads(request.GET.get("groups", "{}"))
        flags = []
        for feature_flag in feature_flags:
            my_overrides = feature_flag.my_overrides  # type: ignore
            override = None
            if len(my_overrides) > 0:
                override = my_overrides[0]

            match = feature_flag.matches(request.user.distinct_id, groups)
            value_for_user_without_override = (match.variant or True) if match else False

            flags.append(
                {
                    "feature_flag": FeatureFlagSerializer(feature_flag).data,
                    "value_for_user_without_override": value_for_user_without_override,
                    "override": FeatureFlagOverrideSerializer(override).data if override else None,
                }
            )
        return Response(flags)


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
        self._ensure_team_and_feature_flag_match(validated_data)
        feature_flag_override, created = FeatureFlagOverride.objects.update_or_create(
            feature_flag=validated_data["feature_flag"],
            user=validated_data["user"],
            team_id=self.context["team_id"],
            defaults={"override_value": validated_data["override_value"]},
        )
        request = self.context["request"]
        if created:
            report_user_action(
                request.user, self._analytics_created_event_name, feature_flag_override.get_analytics_metadata(),
            )
        else:
            report_user_action(
                request.user, self._analytics_updated_event_name, feature_flag_override.get_analytics_metadata(),
            )
        return feature_flag_override

    def update(self, instance: FeatureFlagOverride, validated_data: Dict) -> FeatureFlagOverride:
        self._ensure_team_and_feature_flag_match(validated_data)
        request = self.context["request"]
        instance = super().update(instance, validated_data)
        report_user_action(request.user, self._analytics_updated_event_name, instance.get_analytics_metadata())
        return instance

    def _ensure_team_and_feature_flag_match(self, validated_data: Dict):
        if validated_data["feature_flag"].team_id != self.context["team_id"]:
            raise exceptions.PermissionDenied()


class FeatureFlagOverrideViewset(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.GenericViewSet):
    queryset = FeatureFlagOverride.objects.all()
    serializer_class = FeatureFlagOverrideSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        TemporaryTokenAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    include_in_docs = False

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().filter(user=self.request.user)

    @action(methods=["POST"], detail=False)
    def my_overrides(self, request: request.Request, **kwargs):
        if request.method == "POST":
            user = request.user
            serializer = FeatureFlagOverrideSerializer(
                data={**request.data, "user": user.id}, context={**self.get_serializer_context()},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)


class LegacyFeatureFlagViewSet(FeatureFlagViewSet):
    legacy_team_compatibility = True
