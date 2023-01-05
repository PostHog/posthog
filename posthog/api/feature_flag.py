import json
from typing import Any, Dict, List, Optional, cast

from django.db.models import QuerySet
from rest_framework import authentication, exceptions, request, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.event_usage import report_user_action
from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import Detail, changes_between, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.cohort import Cohort
from posthog.models.feature_flag import (
    FeatureFlagMatcher,
    can_user_edit_feature_flag,
    get_active_feature_flags,
    get_user_blast_radius,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import Property
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class CanEditFeatureFlag(BasePermission):
    message = "You don't have edit permissions for this feature flag."

    def has_object_permission(self, request: Request, view, feature_flag) -> bool:
        if request.method in SAFE_METHODS:
            return True
        else:
            return can_user_edit_feature_flag(request, feature_flag)


class FeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # :TRICKY: Needed for backwards compatibility
    filters = serializers.DictField(source="get_filters", required=False)
    is_simple_flag = serializers.SerializerMethodField()
    rollout_percentage = serializers.SerializerMethodField()

    experiment_set: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="contains the description for the flag (field name `name` is kept for backwards-compatibility)",
    )
    can_edit = serializers.SerializerMethodField()

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
            "experiment_set",
            "rollback_conditions",
            "performed_rollback",
            "can_edit",
        ]

    def get_can_edit(self, feature_flag: FeatureFlag) -> bool:
        # TODO: make sure this isn't n+1
        return can_user_edit_feature_flag(self.context["request"], feature_flag)

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

        variant_list = (filters.get("multivariate") or {}).get("variants", [])
        variants = {variant["key"] for variant in variant_list}

        for condition in filters["groups"]:
            if condition.get("variant") and condition["variant"] not in variants:
                raise serializers.ValidationError("Filters are not valid (variant override does not exist)")

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

        report_user_action(request.user, "feature flag created", instance.get_analytics_metadata())

        return instance

    def update(self, instance: FeatureFlag, validated_data: Dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_key = validated_data.get("key", None)
        if validated_key:
            FeatureFlag.objects.filter(key=validated_key, team=instance.team, deleted=True).delete()
        self._update_filters(validated_data)
        instance = super().update(instance, validated_data)
        instance.update_cohorts()

        report_user_action(request.user, "feature flag updated", instance.get_analytics_metadata())
        return instance

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")

        active = validated_data.get("active", None)
        if active:
            validated_data["performed_rollback"] = False


class MinimalFeatureFlagSerializer(serializers.HyperlinkedModelSerializer):
    filters = serializers.DictField(source="get_filters", required=False)

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "ensure_experience_continuity",
        ]


class FeatureFlagViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

    If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
    """

    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
        CanEditFeatureFlag,
    ]
    authentication_classes = [
        PersonalAPIKeyAuthentication,
        TemporaryTokenAuthentication,  # Allows endpoint to be called from the Toolbar
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()

        if self.action == "list":
            queryset = queryset.filter(deleted=False).prefetch_related("experiment_set")

        return queryset.select_related("created_by").order_by("-created_at")

    @action(methods=["GET"], detail=False)
    def my_flags(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        feature_flags = (
            FeatureFlag.objects.filter(team=self.team, active=True, deleted=False)
            .prefetch_related("experiment_set")
            .select_related("created_by")
            .order_by("-created_at")
        )
        groups = json.loads(request.GET.get("groups", "{}"))
        flags: List[dict] = []

        feature_flag_list = list(feature_flags)

        if not feature_flag_list:
            return Response(flags)

        matches, _, _ = FeatureFlagMatcher(feature_flag_list, request.user.distinct_id, groups).get_matches()
        for feature_flag in feature_flags:
            flags.append(
                {
                    "feature_flag": FeatureFlagSerializer(feature_flag, context=self.get_serializer_context()).data,
                    "value": matches.get(feature_flag.key, False),
                }
            )

        return Response(flags)

    @action(methods=["GET"], detail=False)
    def local_evaluation(self, request: request.Request, **kwargs):

        feature_flags: QuerySet[FeatureFlag] = FeatureFlag.objects.filter(team=self.team, deleted=False)

        parsed_flags = []
        for feature_flag in feature_flags:
            filters = feature_flag.get_filters()
            if len(feature_flag.cohort_ids) == 1:
                feature_flag.filters = {
                    **filters,
                    "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(),
                }
            else:
                feature_flag.filters = filters
            parsed_flags.append(feature_flag)

        return Response(
            {
                "flags": [
                    MinimalFeatureFlagSerializer(feature_flag, context=self.get_serializer_context()).data
                    for feature_flag in parsed_flags
                ],
                "group_type_mapping": {
                    str(row.group_type_index): row.group_type
                    for row in GroupTypeMapping.objects.filter(team_id=self.team_id)
                },
            }
        )

    @action(methods=["GET"], detail=False)
    def evaluation_reasons(self, request: request.Request, **kwargs):

        distinct_id = request.query_params.get("distinct_id", None)
        groups = json.loads(request.query_params.get("groups", "{}"))

        if not distinct_id:
            raise exceptions.ValidationError(detail="distinct_id is required")

        flags, reasons = get_active_feature_flags(self.team_id, distinct_id, groups)

        flags_with_evaluation_reasons = {}

        for flag_key in reasons:
            flags_with_evaluation_reasons[flag_key] = {
                "value": flags.get(flag_key, False),
                "evaluation": reasons[flag_key],
            }

        disabled_flags = FeatureFlag.objects.filter(team_id=self.team_id, active=False, deleted=False).values_list(
            "key", flat=True
        )

        for flag_key in disabled_flags:
            flags_with_evaluation_reasons[flag_key] = {
                "value": False,
                "evaluation": {
                    "reason": "disabled",
                    "condition_index": None,
                },
            }

        return Response(flags_with_evaluation_reasons)

    @action(methods=["POST"], detail=False)
    def user_blast_radius(self, request: request.Request, **kwargs):

        if "condition" not in request.data:
            raise exceptions.ValidationError("Missing condition for which to get blast radius")

        condition = request.data.get("condition") or {}
        group_type_index = request.data.get("group_type_index", None)

        users_affected, total_users = get_user_blast_radius(self.team, condition, group_type_index)

        return Response(
            {
                "users_affected": users_affected,
                "total_users": total_users,
            }
        )

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="FeatureFlag", team_id=self.team_id, limit=limit, page=page)

        return activity_page_response(activity_page, limit, page, request)

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
        return activity_page_response(activity_page, limit, page, request)

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


class LegacyFeatureFlagViewSet(FeatureFlagViewSet):
    legacy_team_compatibility = True
