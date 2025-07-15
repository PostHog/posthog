import json
import re
import time
import logging
from typing import Any, Optional, cast
from datetime import datetime
from django.db import transaction
from django.db.models import QuerySet, Q, deletion, Prefetch
from django.conf import settings
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import (
    exceptions,
    request,
    serializers,
    status,
    viewsets,
)
from posthog.api.utils import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.exceptions_capture import capture_exception
from posthog.api.cohort import CohortSerializer
from posthog.models.experiment import Experiment
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from posthog.api.documentation import extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.dashboards.dashboard import Dashboard
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication, ProjectSecretAPIKeyAuthentication
from posthog.constants import FlagRequestType, SURVEY_TARGETING_FLAG_PREFIX
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict
from posthog.helpers.dashboard_templates import (
    add_enriched_insights_to_feature_flag_dashboard,
)
from posthog.helpers.encrypted_flag_payloads import (
    encrypt_flag_payloads,
    get_decrypted_flag_payloads,
    REDACTED_PAYLOAD_VALUE,
)
from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import (
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.activity_logging.model_activity import ImpersonatedContext
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
from posthog.models.surveys.survey import Survey
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import Property
from posthog.models.feature_flag.flag_status import FeatureFlagStatusChecker, FeatureFlagStatus
from posthog.permissions import ProjectSecretAPITokenPermission
from posthog.queries.base import (
    determine_parsed_date_for_property_matching,
)
from posthog.rate_limit import BurstRateThrottle
from ee.models.rbac.organization_resource_access import OrganizationResourceAccess
from django.dispatch import receiver
from posthog.models.signals import model_activity_signal

DATABASE_FOR_LOCAL_EVALUATION = (
    "default"
    if ("local_evaluation" not in settings.READ_REPLICA_OPT_IN or "replica" not in settings.DATABASES)
    else "replica"
)

BEHAVIOURAL_COHORT_FOUND_ERROR_CODE = "behavioral_cohort_found"

MAX_PROPERTY_VALUES = 1000


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
            # TODO(@zach): Add new access control support
            return can_user_edit_feature_flag(request, feature_flag)


class FeatureFlagSerializer(
    TaggedItemSerializerMixin, UserAccessControlSerializerMixin, serializers.HyperlinkedModelSerializer
):
    created_by = UserBasicSerializer(read_only=True)
    version = serializers.IntegerField(required=False, default=0)
    last_modified_by = UserBasicSerializer(read_only=True)

    # :TRICKY: Needed for backwards compatibility
    filters = serializers.DictField(source="get_filters", required=False)
    is_simple_flag = serializers.SerializerMethodField()
    rollout_percentage = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    ensure_experience_continuity = ClassicBehaviorBooleanFieldSerializer()
    has_enriched_analytics = ClassicBehaviorBooleanFieldSerializer()

    experiment_set = serializers.SerializerMethodField()
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

    CREATION_CONTEXT_CHOICES = ("feature_flags", "experiments", "surveys", "early_access_features", "web_experiments")
    creation_context = serializers.ChoiceField(
        choices=CREATION_CONTEXT_CHOICES,
        write_only=True,
        required=False,
        help_text="Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments'.",
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

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
            "version",
            "last_modified_by",
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
            "user_access_level",
            "creation_context",
            "is_remote_configuration",
            "has_encrypted_payloads",
            "status",
            "_create_in_folder",
        ]

    def get_can_edit(self, feature_flag: FeatureFlag) -> bool:
        # TODO: make sure this isn't n+1
        return (
            # Old access control
            can_user_edit_feature_flag(self.context["request"], feature_flag)
            or
            # New access control
            (
                self.get_user_access_level(feature_flag) == "editor"
                and
                # This is an added check for mid-migration to the new access control. We want to check
                # if the user has permissions from either system but in the case they are still using
                # the old system, since the new system defaults to editor we need to check what that
                # organization is defaulting to for access (view or edit)
                not OrganizationResourceAccess.objects.filter(
                    organization=self.context["request"].user.organization,
                    resource="feature flags",
                    access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
                ).exists()
            )
        )

    # Simple flags are ones that only have rollout_percentage
    # That means server side libraries are able to gate these flags without calling to the server
    def get_is_simple_flag(self, feature_flag: FeatureFlag) -> bool:
        no_properties_used = all(len(condition.get("properties", [])) == 0 for condition in feature_flag.conditions)
        return (
            len(feature_flag.conditions) == 1
            and no_properties_used
            and feature_flag.aggregation_group_type_index is None
        )

    def get_features(self, feature_flag: FeatureFlag) -> dict:
        from products.early_access_features.backend.api import MinimalEarlyAccessFeatureSerializer

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
            FeatureFlag.objects.filter(key=value, team__project_id=self.context["project_id"], deleted=False)
            .exclude(**exclude_kwargs)
            .exists()
        ):
            raise serializers.ValidationError("There is already a feature flag with this key.", code="unique")

        if not re.match(r"^[a-zA-Z0-9_-]+$", value):
            raise serializers.ValidationError(
                "Only letters, numbers, hyphens (-) & underscores (_) are allowed.", code="invalid_key"
            )

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

        # Validate rollout percentages for multivariate variants
        if variant_list:
            variant_rollout_sum = sum(variant.get("rollout_percentage", 0) for variant in variant_list)
            if variant_rollout_sum != 100:
                raise serializers.ValidationError(
                    "Invalid variant definitions: Variant rollout percentages must sum to 100.",
                    code="invalid_input",
                )

        for condition in filters["groups"]:
            if condition.get("variant") and condition["variant"] not in variants:
                raise serializers.ValidationError("Filters are not valid (variant override does not exist)")

            for property in condition.get("properties", []):
                prop = Property(**property)
                if isinstance(prop.value, list):
                    upper_limit = MAX_PROPERTY_VALUES
                    if settings.TEST:
                        upper_limit = 10

                    if len(prop.value) > upper_limit:
                        raise serializers.ValidationError(
                            f"Property group expressions of type {prop.key} cannot contain more than {upper_limit} values."
                        )

                if prop.type == "cohort":
                    try:
                        initial_cohort: Cohort = Cohort.objects.get(
                            pk=prop.value, team__project_id=self.context["project_id"]
                        )
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

        for value in payloads.values():
            try:
                if isinstance(value, str):
                    json_value = json.loads(value)
                else:
                    json_value = value
                json.dumps(json_value)

            except json.JSONDecodeError:
                raise serializers.ValidationError("Payload value is not valid JSON")

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
        project_id = self.context["project_id"]

        try:
            check_flag_evaluation_query_is_ok(temporary_flag, project_id)
        except Exception:
            raise serializers.ValidationError("Can't evaluate flag - please check release conditions")

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["last_modified_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        validated_data["version"] = 1  # This is the first version of the feature flag
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        creation_context = validated_data.pop(
            "creation_context", "feature_flags"
        )  # default to "feature_flags" if an alternative value is not provided

        self._update_filters(validated_data)
        encrypt_flag_payloads(validated_data)

        try:
            FeatureFlag.objects.filter(
                key=validated_data["key"], team__project_id=self.context["project_id"], deleted=True
            ).delete()
        except deletion.RestrictedError:
            raise exceptions.ValidationError(
                "Feature flag with this key already exists and is used in an experiment. Please delete the experiment before deleting the flag."
            )

        analytics_dashboards = validated_data.pop("analytics_dashboards", None)

        self.check_flag_evaluation(validated_data)

        with ImpersonatedContext(request):
            instance: FeatureFlag = super().create(validated_data)

        self._attempt_set_tags(tags, instance)

        _create_usage_dashboard(instance, request.user)

        if analytics_dashboards is not None:
            for dashboard in analytics_dashboards:
                FeatureFlagDashboards.objects.get_or_create(dashboard=dashboard, feature_flag=instance)

        analytics_metadata = instance.get_analytics_metadata()
        analytics_metadata["creation_context"] = creation_context
        report_user_action(request.user, "feature flag created", analytics_metadata)

        return instance

    def update(self, instance: FeatureFlag, validated_data: dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        # This is a workaround to ensure update works when called from a scheduled task.
        if request and not hasattr(request, "data"):
            request.data = {}

        validated_data["last_modified_by"] = request.user

        if "deleted" in validated_data and validated_data["deleted"] is True:
            # Check for linked early access features
            if instance.features.count() > 0:
                raise exceptions.ValidationError(
                    "Cannot delete a feature flag that is in use with early access features. Please delete the early access feature before deleting the flag."
                )

            # Check for linked active (non-deleted) experiments
            active_experiments = instance.experiment_set.filter(deleted=False)
            if active_experiments.exists():
                experiment_ids = list(active_experiments.values_list("id", flat=True))
                raise exceptions.ValidationError(
                    f"Cannot delete a feature flag that is linked to active experiment(s) with ID(s): {', '.join(map(str, experiment_ids))}. Please delete the experiment(s) before deleting the flag."
                )

            # If all experiments are soft-deleted, rename the key to free it up
            # Append ID to the key when soft-deleting to prevent key conflicts
            # This allows the original key to be reused while preserving referential integrity for deleted experiments
            if instance.experiment_set.filter(deleted=True).exists():
                validated_data["key"] = f"{instance.key}:deleted:{instance.id}"

        # First apply all transformations to validated_data
        validated_key = validated_data.get("key", None)
        old_key = instance.key
        self._update_filters(validated_data)

        # TRICKY: Update super_groups if key is changing, since the super groups depend on the key name.
        if validated_key and validated_key != old_key:
            filters = validated_data.get("filters", instance.filters) or {}
            validated_data["filters"] = self._update_super_groups_for_key_change(validated_key, old_key, filters)

        if validated_data.get("has_encrypted_payloads", False):
            if validated_data["filters"]["payloads"]["true"] == REDACTED_PAYLOAD_VALUE:
                # Don't write the redacted payload to the db, keep the current value instead
                validated_data["filters"]["payloads"]["true"] = instance.filters["payloads"]["true"]
            else:
                encrypt_flag_payloads(validated_data)

        version = request.data.get("version", -1)

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic
            locked_instance = FeatureFlag.objects.select_for_update().get(pk=instance.pk)
            locked_version = locked_instance.version or 0

            # NOW check for conflicts after all transformations
            if version != -1 and version != locked_version:
                conflicting_changes = self._get_conflicting_changes(
                    locked_instance, validated_data, request.data.get("original_flag", {})
                )
                if len(conflicting_changes) > 0:
                    raise Conflict(
                        f"The feature flag was updated by {locked_instance.last_modified_by.email if locked_instance.last_modified_by else 'another user'} since you started editing it. Please refresh and try again."
                    )

            # Continue with the update
            validated_data["version"] = locked_version + 1
            old_key = instance.key

            with ImpersonatedContext(request):
                instance = super().update(instance, validated_data)

        # Continue with the update outside of the transaction. This is an intentional choice
        # to avoid deadlocks. Not to mention, before making the concurrency changes, these
        # updates were already occurring outside of a transaction.
        analytics_dashboards = validated_data.pop("analytics_dashboards", None)

        if analytics_dashboards is not None:
            for dashboard in analytics_dashboards:
                FeatureFlagDashboards.objects.get_or_create(dashboard=dashboard, feature_flag=instance)

        # Propagate the new variants and aggregation group type index to the linked experiments
        if "filters" in validated_data:
            filters = validated_data["filters"] or {}
            multivariate = filters.get("multivariate") or {}
            variants = multivariate.get("variants", [])
            aggregation_group_type_index = filters.get("aggregation_group_type_index")

            for experiment in instance.experiment_set.all():
                if experiment.parameters is None:
                    experiment.parameters = {}
                experiment.parameters["feature_flag_variants"] = variants
                if aggregation_group_type_index is not None:
                    experiment.parameters["aggregation_group_type_index"] = aggregation_group_type_index
                else:
                    experiment.parameters.pop("aggregation_group_type_index", None)
                experiment.save()

        if old_key != instance.key:
            _update_feature_flag_dashboard(instance, old_key)

        report_user_action(request.user, "feature flag updated", instance.get_analytics_metadata())

        # If flag is using encrypted payloads, replace them with redacted string or unencrypted value
        # if the request was made with a personal API key
        if instance.has_encrypted_payloads:
            instance.filters["payloads"] = get_decrypted_flag_payloads(request, instance.filters.get("payloads", {}))

        return instance

    def _get_conflicting_changes(
        self, current_instance: FeatureFlag, validated_data: dict, original_flag: dict | None
    ) -> list[str]:
        """
        Returns the list of fields that have conflicts. A conflict is defined as a field that
        the current user is trying to change that has been changed by another user.

        If the field in validated_data is different from the original_flag, then the current user
        is trying to change it.

        If a field that the user is trying to change is different in the current_instance, then
        there is a conflict.
        """

        if original_flag is None or original_flag == {}:
            return []

        # Get the fields that the user is trying to change
        user_changes = [
            field
            for field, new_value in validated_data.items()
            if field in original_flag and new_value != original_flag[field]
        ]

        # Return the fields that have conflicts
        # Only include fields where the user's intended change is different from the current value
        # AND the original value is different from the current value (indicating someone else changed it)
        return [
            field
            for field in user_changes
            if field in original_flag
            and original_flag[field] != getattr(current_instance, field)
            and validated_data[field] != getattr(current_instance, field)
        ]

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")

        active = validated_data.get("active", None)
        if active:
            validated_data["performed_rollback"] = False

    def get_status(self, feature_flag: FeatureFlag) -> str:
        checker = FeatureFlagStatusChecker(feature_flag=feature_flag)
        flag_status, _ = checker.get_status()
        return flag_status.name

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        filters = representation.get("filters", {})
        groups = filters.get("groups", [])

        # Get all cohort IDs used in the feature flag
        cohort_ids = set()
        for group in groups:
            for property in group.get("properties", []):
                if property.get("type") == "cohort":
                    cohort_ids.add(property.get("value"))

        # Use prefetched cohorts if available
        if hasattr(instance.team, "available_cohorts"):
            cohorts = {
                str(cohort.id): cohort.name
                for cohort in instance.team.available_cohorts
                if str(cohort.id) in map(str, cohort_ids)
            }
        else:
            # Fallback to database query if cohorts weren't prefetched
            cohorts = {
                str(cohort.id): cohort.name
                for cohort in Cohort.objects.filter(id__in=cohort_ids, team__project_id=self.context["project_id"])
            }

        # Add cohort names to the response
        for group in groups:
            for property in group.get("properties", []):
                if property.get("type") == "cohort":
                    property["cohort_name"] = cohorts.get(str(property.get("value")))

        representation["filters"] = filters
        return representation

    def get_experiment_set(self, obj):
        # Use the prefetched active experiments
        if hasattr(obj, "_active_experiments"):
            return [exp.id for exp in obj._active_experiments]
        return [exp.id for exp in obj.experiment_set.filter(deleted=False)]

    def _update_super_groups_for_key_change(self, validated_key: str, old_key: str, filters: dict) -> dict:
        if not (validated_key and validated_key != old_key and "super_groups" in filters):
            return filters

        updated_filters = filters.copy()
        updated_filters["super_groups"] = [
            {
                **group,
                "properties": [
                    {
                        **prop,
                        "key": f"$feature_enrollment/{validated_key}"
                        if prop.get("key", "").startswith("$feature_enrollment/")
                        else prop["key"],
                    }
                    for prop in group.get("properties", [])
                ],
            }
            for group in filters["super_groups"]
        ]
        return updated_filters


def _create_usage_dashboard(feature_flag: FeatureFlag, user):
    from posthog.helpers.dashboard_templates import create_feature_flag_dashboard
    from posthog.models.dashboard import Dashboard

    usage_dashboard = Dashboard.objects.create(
        name="Generated Dashboard: " + feature_flag.key + " Usage",
        description="This dashboard was generated by the feature flag with key (" + feature_flag.key + ")",
        team=feature_flag.team,
        created_by=user,
        creation_mode="template",
    )
    create_feature_flag_dashboard(feature_flag, usage_dashboard, user)

    feature_flag.usage_dashboard = usage_dashboard
    feature_flag.save()

    return usage_dashboard


def _update_feature_flag_dashboard(feature_flag: FeatureFlag, old_key: str) -> None:
    from posthog.helpers.dashboard_templates import update_feature_flag_dashboard

    if not old_key:
        return

    update_feature_flag_dashboard(feature_flag, old_key)


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
            "has_encrypted_payloads",
            "version",
        ]


class FeatureFlagViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    """
    Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

    If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
    """

    scope_object = "feature_flag"
    queryset = FeatureFlag.objects.all()
    serializer_class = FeatureFlagSerializer
    permission_classes = [CanEditFeatureFlag]
    authentication_classes = [
        TemporaryTokenAuthentication,  # Allows endpoint to be called from the Toolbar
    ]

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "active":
                queryset = queryset.filter(active=filters[key] == "true")
            elif key == "created_by_id":
                queryset = queryset.filter(created_by_id=request.GET["created_by_id"])
            elif key == "search":
                queryset = queryset.filter(
                    Q(key__icontains=request.GET["search"]) | Q(name__icontains=request.GET["search"])
                )
            elif key == "type":
                type = request.GET["type"]
                if type == "boolean":
                    queryset = queryset.filter(
                        Q(filters__multivariate__variants__isnull=True) | Q(filters__multivariate__variants=[])
                    )
                elif type == "multivariant":
                    queryset = queryset.filter(
                        Q(filters__multivariate__variants__isnull=False) & ~Q(filters__multivariate__variants=[])
                    )
                elif type == "experiment":
                    queryset = queryset.filter(~Q(experiment__isnull=True))
                elif type == "remote_config":
                    queryset = queryset.filter(is_remote_configuration=True)

        return queryset

    def safely_get_queryset(self, queryset) -> QuerySet:
        # Always prefetch experiment_set since it's used in both list and retrieve
        queryset = queryset.prefetch_related(
            Prefetch("experiment_set", queryset=Experiment.objects.filter(deleted=False), to_attr="_active_experiments")
        )

        if self.action == "list":
            queryset = (
                queryset.filter(deleted=False)
                .prefetch_related("features")
                .prefetch_related("analytics_dashboards")
                .prefetch_related("surveys_linked_flag")
                .prefetch_related(
                    Prefetch(
                        "team__cohort_set",
                        queryset=Cohort.objects.filter(deleted=False).only("id", "name"),
                        to_attr="available_cohorts",
                    )
                )
            )

            survey_targeting_flags = Survey.objects.filter(
                team__project_id=self.project_id, targeting_flag__isnull=False
            ).values_list("targeting_flag_id", flat=True)
            survey_internal_targeting_flags = Survey.objects.filter(
                team__project_id=self.project_id, internal_targeting_flag__isnull=False
            ).values_list("internal_targeting_flag_id", flat=True)
            queryset = queryset.exclude(Q(id__in=survey_targeting_flags)).exclude(
                Q(id__in=survey_internal_targeting_flags)
            )

            # add additional filters provided by the client
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-created_at")

        return queryset.select_related("created_by", "last_modified_by")

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "active",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["true", "false"],
            ),
            OpenApiParameter(
                "created_by_id",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="The User ID which initially created the feature flag.",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search by feature flag key or name. Case insensitive.",
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["boolean", "multivariant", "experiment"],
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        if isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            # Add request for analytics only if request coming with personal API key authentication
            increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

        response = super().list(request, *args, **kwargs)
        feature_flags_data = response.data.get("results", [])

        # If flag is using encrypted payloads, replace them with redacted string or unencrypted value
        for feature_flag in feature_flags_data:
            if feature_flag.get("has_encrypted_payloads", False):
                feature_flag["filters"]["payloads"] = get_decrypted_flag_payloads(
                    request, feature_flag["filters"]["payloads"]
                )

        return response

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        feature_flag_data = response.data

        # If flag is using encrypted payloads, replace them with redacted string or unencrypted value
        if feature_flag_data.get("has_encrypted_payloads", False):
            feature_flag_data["filters"]["payloads"] = get_decrypted_flag_payloads(
                request, feature_flag_data["filters"]["payloads"]
            )

        return response

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

        feature_flags = list(
            FeatureFlag.objects.filter(team__project_id=self.project_id, deleted=False).order_by("-created_at")
        )

        if not feature_flags:
            return Response([])

        groups = json.loads(request.GET.get("groups", "{}"))
        matches, *_ = get_all_feature_flags(self.team, request.user.distinct_id, groups)

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
        methods=["GET"],
        detail=False,
        throttle_classes=[FeatureFlagThrottle],
        required_scopes=["feature_flag:read"],
        authentication_classes=[TemporaryTokenAuthentication, ProjectSecretAPIKeyAuthentication],
        permission_classes=[ProjectSecretAPITokenPermission],
    )
    def local_evaluation(self, request: request.Request, **kwargs):
        logger = logging.getLogger(__name__)
        start_time = time.time()

        try:
            # Check if team is quota limited for feature flags
            if settings.DECIDE_FEATURE_FLAG_QUOTA_CHECK:
                from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

                limited_tokens_flags = list_limited_team_attributes(
                    QuotaResource.FEATURE_FLAG_REQUESTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
                )
                if self.team.api_token in limited_tokens_flags:
                    return Response(
                        {
                            "type": "quota_limited",
                            "detail": "You have exceeded your feature flag request quota",
                            "code": "payment_required",
                        },
                        status=status.HTTP_402_PAYMENT_REQUIRED,
                    )

            logger.info(
                "Starting local evaluation",
                extra={
                    "team_id": self.team.pk,
                    "has_send_cohorts": "send_cohorts" in request.GET,
                },
            )

            try:
                feature_flags = FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                    ~Q(is_remote_configuration=True),
                    team__project_id=self.project_id,
                    deleted=False,
                )
                logger.info("Retrieved feature flags", extra={"flags_count": len(feature_flags)})
            except Exception as e:
                logger.error("Error fetching feature flags", exc_info=True)
                capture_exception(e)
                return Response(
                    {
                        "type": "server_error",
                        "code": "feature_flags_fetch_failed",
                        "detail": "Error fetching feature flags",
                    },
                    status=500,
                )

            should_send_cohorts = "send_cohorts" in request.GET
            cohorts = {}
            seen_cohorts_cache: dict[int, CohortOrEmpty] = {}

            if should_send_cohorts:
                try:
                    seen_cohorts_cache = {
                        cohort.pk: cohort
                        for cohort in Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                            team__project_id=self.project_id, deleted=False
                        )
                    }
                    logger.info("Prefetched cohorts", extra={"cohorts_count": len(seen_cohorts_cache)})
                except Exception as e:
                    logger.error("Error prefetching cohorts", exc_info=True)
                    capture_exception(e)
                    return Response(
                        {
                            "type": "server_error",
                            "code": "cohorts_fetch_failed",
                            "detail": "Error fetching cohorts",
                        },
                        status=500,
                    )

            parsed_flags = []
            for feature_flag in feature_flags:
                try:
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
                        try:
                            cohort_ids = feature_flag.get_cohort_ids(
                                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                                seen_cohorts_cache=seen_cohorts_cache,
                            )

                            for id in cohort_ids:
                                # don't duplicate queries for already added cohorts
                                if id not in cohorts:
                                    if id in seen_cohorts_cache:
                                        cohort = seen_cohorts_cache[id]
                                    else:
                                        cohort = (
                                            Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
                                            .filter(id=id, team__project_id=self.project_id, deleted=False)
                                            .first()
                                        )
                                        seen_cohorts_cache[id] = cohort or ""

                                    if cohort and not cohort.is_static:
                                        try:
                                            cohorts[str(cohort.pk)] = cohort.properties.to_dict()
                                        except Exception:
                                            logger.error(
                                                "Error processing cohort properties",
                                                extra={"cohort_id": id},
                                                exc_info=True,
                                            )
                                            continue

                        except Exception:
                            logger.error(
                                "Error processing cohorts for feature flag",
                                extra={"flag_id": feature_flag.pk},
                                exc_info=True,
                            )
                            continue

                except Exception:
                    logger.error("Error processing feature flag", extra={"flag_id": feature_flag.pk}, exc_info=True)
                    continue

            # Add request for analytics
            if len(parsed_flags) > 0 and not all(
                flag.key.startswith(SURVEY_TARGETING_FLAG_PREFIX) for flag in parsed_flags
            ):
                increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

            duration = time.time() - start_time
            logger.info(
                "Local evaluation complete",
                extra={"duration": duration, "flags_count": len(parsed_flags), "cohorts_count": len(cohorts)},
            )

            try:
                response_data = {
                    "flags": [
                        MinimalFeatureFlagSerializer(feature_flag, context=self.get_serializer_context()).data
                        for feature_flag in parsed_flags
                    ],
                    "group_type_mapping": {
                        str(row.group_type_index): row.group_type
                        for row in GroupTypeMapping.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                            project_id=self.project_id
                        )
                    },
                    "cohorts": cohorts,
                }
                return Response(response_data)

            except Exception as e:
                logger.error("Error serializing response", exc_info=True)
                capture_exception(e)
                return Response(
                    {
                        "type": "server_error",
                        "code": "serialization_failed",
                        "detail": "Error preparing response",
                    },
                    status=500,
                )

        except Exception as e:
            duration = time.time() - start_time
            logger.error("Unexpected error in local evaluation", extra={"duration": duration}, exc_info=True)
            capture_exception(e)
            return Response(
                {
                    "type": "server_error",
                    "code": "unexpected_error",
                    "detail": "An unexpected error occurred",
                },
                status=500,
            )

    @action(methods=["GET"], detail=False)
    def evaluation_reasons(self, request: request.Request, **kwargs):
        distinct_id = request.query_params.get("distinct_id", None)
        groups = json.loads(request.query_params.get("groups", "{}"))

        if not distinct_id:
            raise exceptions.ValidationError(detail="distinct_id is required")

        flags, reasons, _, _ = get_all_feature_flags(self.team, distinct_id, groups)

        flags_with_evaluation_reasons = {}

        for flag_key in reasons:
            flags_with_evaluation_reasons[flag_key] = {
                "value": flags.get(flag_key, False),
                "evaluation": reasons[flag_key],
            }

        disabled_flags = FeatureFlag.objects.filter(
            team__project_id=self.project_id, active=False, deleted=False
        ).values_list("key", flat=True)

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
                "name": f"Users with feature flag {feature_flag_key} enabled at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
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

    @action(methods=["GET"], detail=True, required_scopes=["feature_flag:read"])
    def status(self, request: request.Request, **kwargs):
        feature_flag_id = kwargs["pk"]

        checker = FeatureFlagStatusChecker(
            feature_flag_id=feature_flag_id,
        )
        flag_status, reason = checker.get_status()

        return Response(
            {"status": flag_status, "reason": reason},
            status=status.HTTP_404_NOT_FOUND if flag_status == FeatureFlagStatus.UNKNOWN else status.HTTP_200_OK,
        )

    @action(
        methods=["GET"],
        detail=True,
        required_scopes=["feature_flag:read"],
        authentication_classes=[TemporaryTokenAuthentication, ProjectSecretAPIKeyAuthentication],
        permission_classes=[ProjectSecretAPITokenPermission],
    )
    def remote_config(self, request: request.Request, **kwargs):
        is_flag_id_provided = kwargs["pk"].isdigit()

        try:
            feature_flag = (
                FeatureFlag.objects.get(pk=kwargs["pk"])
                if is_flag_id_provided
                else FeatureFlag.objects.get(key=kwargs["pk"], team__project_id=self.project_id)
            )
        except FeatureFlag.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not feature_flag.is_remote_configuration:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not feature_flag.has_encrypted_payloads:
            payloads = feature_flag.filters.get("payloads", {})
            return Response(payloads.get("true") or None)

        # Note: This decryption step is protected by the feature_flag:read scope, so we can assume the
        # user has access to the flag. However get_decrypted_flag_payloads will also check the authentication
        # method used to make the request as it is used in non-protected endpoints.
        decrypted_flag_payloads = get_decrypted_flag_payloads(request, feature_flag.filters.get("payloads", {}))

        count = int(1 / settings.DECIDE_BILLING_SAMPLING_RATE)
        increment_request_count(self.team.pk, count, FlagRequestType.REMOTE_CONFIG)

        return Response(decrypted_flag_payloads["true"] or None)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not FeatureFlag.objects.filter(id=item_id, team__project_id=self.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="FeatureFlag",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


@receiver(model_activity_signal, sender=FeatureFlag)
def handle_feature_flag_change(sender, scope, before_update, after_update, activity, was_impersonated=False, **kwargs):
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.last_modified_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update), name=after_update.key
        ),
    )


class LegacyFeatureFlagViewSet(FeatureFlagViewSet):
    param_derived_from_user_current_team = "project_id"
