import json
from typing import Any, Optional, cast
from datetime import datetime

from django.db.models import QuerySet, Q, deletion
from django.conf import settings
from rest_framework import (
    exceptions,
    request,
    serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from sentry_sdk import capture_exception
from posthog.api.cohort import CohortSerializer

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.dashboards.dashboard import Dashboard
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.constants import FlagRequestType
from posthog.event_usage import report_user_action
from posthog.helpers.dashboard_templates import (
    add_enriched_insights_to_feature_flag_dashboard,
)
from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import (
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.cohort.util import get_dependent_cohorts
from posthog.models.feature_flag import (
    FeatureFlagDashboards,
    can_user_edit_feature_flag,
    get_all_feature_flags,
    get_user_blast_radius,
)
from posthog.models.feature_flag.flag_analytics import increment_request_count
from posthog.models.feature_flag.flag_matching import check_flag_evaluation_query_is_ok
from posthog.models.feedback.survey import Survey
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import Property
from posthog.queries.base import (
    determine_parsed_date_for_property_matching,
)
from posthog.rate_limit import BurstRateThrottle
from loginas.utils import is_impersonated_session

DATABASE_FOR_LOCAL_EVALUATION = (
    "default"
    if ("local_evaluation" not in settings.READ_REPLICA_OPT_IN or "replica" not in settings.DATABASES)
    else "replica"
)

BEHAVIOURAL_COHORT_FOUND_ERROR_CODE = "behavioral_cohort_found"


class FeatureFlagThrottle(BurstRateThrottle):
    # Throttle class that's scoped just to the local evaluation endpoint.
    # This makes the rate limit independent of other endpoints.
    scope = "feature_flag_evaluations"
    rate = "600/minute"


class CanEditFeatureFlag(BasePermission):
    message = "You don't have edit permissions for this feature flag."

    def has_object_permission(self, request: Request, view, feature_flag) -> bool:
        if request.method in SAFE_METHODS:
            return True
        else:
            return can_user_edit_feature_flag(request, feature_flag)


class FeatureFlagSerializer(TaggedItemSerializerMixin, serializers.HyperlinkedModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    # :TRICKY: Needed for backwards compatibility
    filters = serializers.DictField(source="get_filters", required=False)
    is_simple_flag = serializers.SerializerMethodField()
    rollout_percentage = serializers.SerializerMethodField()

    ensure_experience_continuity = ClassicBehaviorBooleanFieldSerializer()
    has_enriched_analytics = ClassicBehaviorBooleanFieldSerializer()

    experiment_set: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    surveys: serializers.SerializerMethodField = serializers.SerializerMethodField()
    features: serializers.SerializerMethodField = serializers.SerializerMethodField()
    usage_dashboard: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)
    analytics_dashboards = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=Dashboard.objects.all(),
    )

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
            "surveys",
            "features",
            "rollback_conditions",
            "performed_rollback",
            "can_edit",
            "tags",
            "usage_dashboard",
            "analytics_dashboards",
            "has_enriched_analytics",
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

    def get_features(self, feature_flag: FeatureFlag) -> dict:
        from posthog.api.early_access_feature import MinimalEarlyAccessFeatureSerializer

        return MinimalEarlyAccessFeatureSerializer(feature_flag.features, many=True).data

    def get_surveys(self, feature_flag: FeatureFlag) -> dict:
        from posthog.api.survey import SurveyAPISerializer

        return SurveyAPISerializer(feature_flag.surveys_linked_flag, many=True).data
        # ignoring type because mypy doesn't know about the surveys_linked_flag `related_name` relationship

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
            return self.instance.filters

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
        elif self.instance is not None and hasattr(self.instance, "features") and self.instance.features.count() > 0:
            raise serializers.ValidationError(
                "Cannot change this flag to a group-based when linked to an Early Access Feature."
            )

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
                        initial_cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self.context["team_id"])
                        dependent_cohorts = get_dependent_cohorts(initial_cohort)
                        for cohort in [initial_cohort, *dependent_cohorts]:
                            if [prop for prop in cohort.properties.flat if prop.type == "behavioral"]:
                                raise serializers.ValidationError(
                                    detail=f"Cohort '{cohort.name}' with filters on events cannot be used in feature flags.",
                                    code=BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
                                )
                    except Cohort.DoesNotExist:
                        raise serializers.ValidationError(
                            detail=f"Cohort with id {prop.value} does not exist",
                            code="cohort_does_not_exist",
                        )

                if prop.operator in ("is_date_before", "is_date_after"):
                    parsed_date = determine_parsed_date_for_property_matching(prop.value)

                    if not parsed_date:
                        raise serializers.ValidationError(
                            detail=f"Invalid date value: {prop.value}", code="invalid_date"
                        )

                # make sure regex, icontains, gte, lte, lt, and gt properties have string values
                if prop.operator in [
                    "regex",
                    "icontains",
                    "not_regex",
                    "not_icontains",
                    "gte",
                    "lte",
                    "gt",
                    "lt",
                ] and not isinstance(prop.value, str):
                    raise serializers.ValidationError(
                        detail=f"Invalid value for operator {prop.operator}: {prop.value}", code="invalid_value"
                    )

        payloads = filters.get("payloads", {})

        if not isinstance(payloads, dict):
            raise serializers.ValidationError("Payloads must be passed as a dictionary")

        if filters.get("multivariate"):
            if not all(key in variants for key in payloads):
                raise serializers.ValidationError("Payload keys must match a variant key for multivariate flags")
        else:
            if len(payloads) > 1 or any(key != "true" for key in payloads):  # only expect one key
                raise serializers.ValidationError("Payload keys must be 'true' for boolean flags")

        return filters

    def check_flag_evaluation(self, data):
        # TODO: Once we move to no DB level evaluation, can get rid of this.

        temporary_flag = FeatureFlag(**data)
        team_id = self.context["team_id"]

        try:
            check_flag_evaluation_query_is_ok(temporary_flag, team_id)
        except Exception:
            raise serializers.ValidationError("Can't evaluate flag - please check release conditions")

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships

        self._update_filters(validated_data)

        variants = (validated_data.get("filters", {}).get("multivariate", {}) or {}).get("variants", [])
        variant_rollout_sum = 0
        for variant in variants:
            variant_rollout_sum += variant.get("rollout_percentage")

        if len(variants) > 0 and variant_rollout_sum != 100:
            raise exceptions.ValidationError(
                "Invalid variant definitions: Variant rollout percentages must sum to 100."
            )

        try:
            FeatureFlag.objects.filter(
                key=validated_data["key"], team_id=self.context["team_id"], deleted=True
            ).delete()
        except deletion.RestrictedError:
            raise exceptions.ValidationError(
                "Feature flag with this key already exists and is used in an experiment. Please delete the experiment before deleting the flag."
            )

        self.check_flag_evaluation(validated_data)

        instance: FeatureFlag = super().create(validated_data)

        self._attempt_set_tags(tags, instance)

        _create_usage_dashboard(instance, request.user)

        report_user_action(request.user, "feature flag created", instance.get_analytics_metadata())

        return instance

    def update(self, instance: FeatureFlag, validated_data: dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        if "deleted" in validated_data and validated_data["deleted"] is True and instance.features.count() > 0:
            raise exceptions.ValidationError(
                "Cannot delete a feature flag that is in use with early access features. Please delete the early access feature before deleting the flag."
            )

        request = self.context["request"]
        validated_key = validated_data.get("key", None)
        if validated_key:
            FeatureFlag.objects.filter(key=validated_key, team=instance.team, deleted=True).delete()
        self._update_filters(validated_data)

        analytics_dashboards = validated_data.pop("analytics_dashboards", None)

        if analytics_dashboards is not None:
            for dashboard in analytics_dashboards:
                FeatureFlagDashboards.objects.get_or_create(dashboard=dashboard, feature_flag=instance)

        instance = super().update(instance, validated_data)

        report_user_action(request.user, "feature flag updated", instance.get_analytics_metadata())

        return instance

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")

        active = validated_data.get("active", None)
        if active:
            validated_data["performed_rollback"] = False


def _create_usage_dashboard(feature_flag: FeatureFlag, user):
    from posthog.helpers.dashboard_templates import create_feature_flag_dashboard
    from posthog.models.dashboard import Dashboard

    usage_dashboard = Dashboard.objects.create(
        name="Generated Dashboard: " + feature_flag.key + " Usage",
        description="This dashboard was generated by the feature flag with key (" + feature_flag.key + ")",
        team=feature_flag.team,
        created_by=user,
    )
    create_feature_flag_dashboard(feature_flag, usage_dashboard)

    feature_flag.usage_dashboard = usage_dashboard
    feature_flag.save()

    return usage_dashboard


class MinimalFeatureFlagSerializer(serializers.ModelSerializer):
    filters = serializers.DictField(source="get_filters", required=False)

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "team_id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "ensure_experience_continuity",
        ]


class FeatureFlagViewSet(
    TeamAndOrgViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    """
    Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/user-guides/feature-flags) for more information on feature flags.

    If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
    """

    scope_object = "feature_flag"
    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [CanEditFeatureFlag]
    authentication_classes = [
        TemporaryTokenAuthentication,  # Allows endpoint to be called from the Toolbar
    ]

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = (
                queryset.filter(deleted=False)
                .prefetch_related("experiment_set")
                .prefetch_related("features")
                .prefetch_related("analytics_dashboards")
                .prefetch_related("surveys_linked_flag")
            )

            survey_targeting_flags = Survey.objects.filter(team=self.team, targeting_flag__isnull=False).values_list(
                "targeting_flag_id", flat=True
            )
            survey_internal_targeting_flags = Survey.objects.filter(
                team=self.team, internal_targeting_flag__isnull=False
            ).values_list("internal_targeting_flag_id", flat=True)
            queryset = queryset.exclude(Q(id__in=survey_targeting_flags)).exclude(
                Q(id__in=survey_internal_targeting_flags)
            )

        return queryset.select_related("created_by").order_by("-created_at")

    def list(self, request, *args, **kwargs):
        if isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            # Add request for analytics only if request coming with personal API key authentication
            increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

        return super().list(request, args, kwargs)

    @action(methods=["POST"], detail=True)
    def dashboard(self, request: request.Request, **kwargs):
        feature_flag: FeatureFlag = self.get_object()
        try:
            usage_dashboard = _create_usage_dashboard(feature_flag, request.user)

            if feature_flag.has_enriched_analytics and not feature_flag.usage_dashboard_has_enriched_insights:
                add_enriched_insights_to_feature_flag_dashboard(feature_flag, usage_dashboard)

        except Exception as e:
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "error": f"Unable to generate usage dashboard",
                },
                status=400,
            )

        return Response({"success": True}, status=200)

    @action(methods=["POST"], detail=True)
    def enrich_usage_dashboard(self, request: request.Request, **kwargs):
        feature_flag: FeatureFlag = self.get_object()
        usage_dashboard = feature_flag.usage_dashboard

        if not usage_dashboard:
            return Response(
                {
                    "success": False,
                    "error": f"Usage dashboard not found",
                },
                status=400,
            )

        if feature_flag.usage_dashboard_has_enriched_insights:
            return Response(
                {
                    "success": False,
                    "error": f"Usage dashboard already has enriched data",
                },
                status=400,
            )

        if not feature_flag.has_enriched_analytics:
            return Response(
                {
                    "success": False,
                    "error": f"No enriched analytics available for this feature flag",
                },
                status=400,
            )
        try:
            add_enriched_insights_to_feature_flag_dashboard(feature_flag, usage_dashboard)
        except Exception as e:
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "error": f"Unable to enrich usage dashboard",
                },
                status=400,
            )

        return Response({"success": True}, status=200)

    @action(methods=["GET"], detail=False)
    def my_flags(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        feature_flags = list(FeatureFlag.objects.filter(team=self.team, deleted=False).order_by("-created_at"))

        if not feature_flags:
            return Response([])

        groups = json.loads(request.GET.get("groups", "{}"))
        matches, *_ = get_all_feature_flags(self.team_id, request.user.distinct_id, groups)

        all_serialized_flags = MinimalFeatureFlagSerializer(
            feature_flags, many=True, context=self.get_serializer_context()
        ).data
        return Response(
            {
                "feature_flag": feature_flag,
                "value": matches.get(feature_flag["key"], False),
            }
            for feature_flag in all_serialized_flags
        )

    @action(
        methods=["GET"], detail=False, throttle_classes=[FeatureFlagThrottle], required_scopes=["feature_flag:read"]
    )
    def local_evaluation(self, request: request.Request, **kwargs):
        feature_flags: QuerySet[FeatureFlag] = FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
            team__project_id=self.project_id, deleted=False, active=True
        )

        should_send_cohorts = "send_cohorts" in request.GET

        cohorts = {}
        seen_cohorts_cache: dict[int, CohortOrEmpty] = {}

        if should_send_cohorts:
            seen_cohorts_cache = {
                cohort.pk: cohort
                for cohort in Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                    team_id=self.team_id, deleted=False
                )
            }

        parsed_flags = []
        for feature_flag in feature_flags:
            filters = feature_flag.get_filters()
            # transform cohort filters to be evaluated locally, but only if send_cohorts is false
            if not should_send_cohorts and (
                len(
                    feature_flag.get_cohort_ids(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    )
                )
                == 1
            ):
                feature_flag.filters = {
                    **filters,
                    "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    ),
                }
            else:
                feature_flag.filters = filters

            parsed_flags.append(feature_flag)

            # when param set, send cohorts, for libraries that can handle evaluating them locally
            # irrespective of complexity
            if should_send_cohorts:
                for id in feature_flag.get_cohort_ids(
                    using_database=DATABASE_FOR_LOCAL_EVALUATION,
                    seen_cohorts_cache=seen_cohorts_cache,
                ):
                    # don't duplicate queries for already added cohorts
                    if id not in cohorts:
                        if id in seen_cohorts_cache:
                            cohort = seen_cohorts_cache[id]
                        else:
                            cohort = (
                                Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
                                .filter(id=id, team_id=self.team_id, deleted=False)
                                .first()
                            )
                            seen_cohorts_cache[id] = cohort or ""

                        if cohort and not cohort.is_static:
                            cohorts[str(cohort.pk)] = cohort.properties.to_dict()

        # Add request for analytics
        increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

        return Response(
            {
                "flags": [
                    MinimalFeatureFlagSerializer(feature_flag, context=self.get_serializer_context()).data
                    for feature_flag in parsed_flags
                ],
                "group_type_mapping": {
                    str(row.group_type_index): row.group_type
                    for row in GroupTypeMapping.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                        team_id=self.team_id
                    )
                },
                "cohorts": cohorts,
            }
        )

    @action(methods=["GET"], detail=False)
    def evaluation_reasons(self, request: request.Request, **kwargs):
        distinct_id = request.query_params.get("distinct_id", None)
        groups = json.loads(request.query_params.get("groups", "{}"))

        if not distinct_id:
            raise exceptions.ValidationError(detail="distinct_id is required")

        flags, reasons, _, _ = get_all_feature_flags(self.team_id, distinct_id, groups)

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

        # TODO: Handle distinct_id and $group_key properties, which are not currently supported
        users_affected, total_users = get_user_blast_radius(self.team, condition, group_type_index)

        return Response(
            {
                "users_affected": users_affected,
                "total_users": total_users,
            }
        )

    @action(methods=["POST"], detail=True)
    def create_static_cohort_for_flag(self, request: request.Request, **kwargs):
        feature_flag = self.get_object()
        feature_flag_key = feature_flag.key
        cohort_serializer = CohortSerializer(
            data={
                "is_static": True,
                "key": feature_flag_key,
                "name": f'Users with feature flag {feature_flag_key} enabled at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                "is_calculating": True,
            },
            context={
                "request": request,
                "team": self.team,
                "team_id": self.team_id,
                "from_feature_flag_key": feature_flag_key,
            },
        )

        cohort_serializer.is_valid(raise_exception=True)
        cohort_serializer.save()
        return Response({"cohort": cohort_serializer.data}, status=201)

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="FeatureFlag", team_id=self.team_id, limit=limit, page=page)

        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not FeatureFlag.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response("", status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="FeatureFlag",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    def perform_create(self, serializer):
        serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
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
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance_id,
            scope="FeatureFlag",
            activity="updated",
            detail=Detail(changes=changes, name=serializer.instance.key),
        )


class LegacyFeatureFlagViewSet(FeatureFlagViewSet):
    param_derived_from_user_current_team = "project_id"
