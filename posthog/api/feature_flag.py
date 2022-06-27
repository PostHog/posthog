import json
from typing import Any, Dict, Optional, cast

from django.db.models import Prefetch, QuerySet
from rest_framework import authentication, exceptions, request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.event_usage import report_user_action
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import (
    ActivityPage,
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.serializers import ActivityLogSerializer
from posthog.models.cohort import Cohort
from posthog.models.feature_flag import FeatureFlagOverride
from posthog.models.property import Property
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.utils import format_query_params_absolute_url


class FeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # :TRICKY: Needed for backwards compatibility
    filters = serializers.DictField(source="get_filters", required=False)
    is_simple_flag = serializers.SerializerMethodField()
    rollout_percentage = serializers.SerializerMethodField()
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="contains the description for the flag (field name `name` is kept for backwards-compatibility)",
    )

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
            "ensure_experience_continuity",
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
        # For some weird internal REST framework reason this field gets validated on a partial PATCH call, even if filters isn't being updatd
        # If we see this, just return the current filters
        if "groups" not in filters and self.context["request"].method == "PATCH":
            # mypy cannot tell that self.instance is a FeatureFlag
            return self.instance.filters  # type: ignore

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

        for condition in filters["groups"]:
            for property in condition.get("properties", []):
                prop = Property(**property)
                if prop.type == "cohort":
                    try:
                        cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self.context["team_id"])
                        if [prop for prop in cohort.properties.flat if prop.type == "behavioral"]:
                            raise serializers.ValidationError(
                                detail=f"Cohort '{cohort.name}' with behavioral filters cannot be used in feature flags.",
                                code="behavioral_cohort_found",
                            )
                    except Cohort.DoesNotExist:
                        raise serializers.ValidationError(
                            detail=f"Cohort with id {prop.value} does not exist", code="cohort_does_not_exist"
                        )
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
        instance: FeatureFlag = super().create(validated_data)
        instance.update_cohorts()

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
        instance.update_cohorts()

        report_user_action(
            request.user, "feature flag updated", instance.get_analytics_metadata(),
        )
        return instance

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")


class FeatureFlagViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

    If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
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
            .select_related("created_by")
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

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="FeatureFlag", team_id=self.team_id, limit=limit, page=page)

        return self._return_activity_page(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not FeatureFlag.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response("", status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="FeatureFlag", team_id=self.team_id, item_id=item_id, limit=limit, page=page
        )
        return self._return_activity_page(activity_page, limit, page, request)

    @staticmethod
    def _return_activity_page(activity_page: ActivityPage, limit: int, page: int, request: request.Request) -> Response:
        return Response(
            {
                "results": ActivityLogSerializer(activity_page.results, many=True,).data,
                "next": format_query_params_absolute_url(request, page + 1, limit, offset_alias="page")
                if activity_page.has_next
                else None,
                "previous": format_query_params_absolute_url(request, page - 1, limit, offset_alias="page")
                if activity_page.has_previous
                else None,
                "total_count": activity_page.total_count,
            },
            status=status.HTTP_200_OK,
        )

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            item_id=serializer.instance.id,
            scope="FeatureFlag",
            activity="created",
            detail=Detail(name=serializer.instance.key),
        )

    def perform_update(self, serializer):
        instance_id = serializer.instance.id

        try:
            before_update = FeatureFlag.objects.get(pk=instance_id)
        except FeatureFlag.DoesNotExist:
            before_update = None

        serializer.save()

        changes = changes_between("FeatureFlag", previous=before_update, current=serializer.instance)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            item_id=instance_id,
            scope="FeatureFlag",
            activity="updated",
            detail=Detail(changes=changes, name=serializer.instance.key),
        )


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
