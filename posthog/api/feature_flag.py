from __future__ import annotations

import re
import json
import time
import random
import logging
from datetime import datetime
from typing import Any, Optional, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet, deletion
from django.dispatch import receiver

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import exceptions, request, serializers, status, viewsets
from rest_framework.response import Response
from statshog.defaults.django import statsd

from posthog.schema import PropertyOperator

from posthog.api.cohort import CohortSerializer
from posthog.api.dashboards.dashboard import Dashboard
from posthog.api.documentation import extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin, tagify
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, action
from posthog.auth import PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.constants import SURVEY_TARGETING_FLAG_PREFIX, FlagRequestType
from posthog.date_util import thirty_days_ago
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.helpers.dashboard_templates import add_enriched_insights_to_feature_flag_dashboard
from posthog.helpers.encrypted_flag_payloads import (
    REDACTED_PAYLOAD_VALUE,
    encrypt_flag_payloads,
    get_decrypted_flag_payloads,
)
from posthog.models import FeatureFlag, Tag
from posthog.models.activity_logging.activity_log import Detail, changes_between, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.activity_logging.model_activity import ImpersonatedContext
from posthog.models.cohort import Cohort
from posthog.models.cohort.util import get_all_cohort_dependencies
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import (
    FeatureFlagDashboards,
    FeatureFlagEvaluationTag,
    get_all_feature_flags,
    get_user_blast_radius,
    set_feature_flags_for_team_in_cache,
)
from posthog.models.feature_flag.flag_analytics import increment_request_count
from posthog.models.feature_flag.flag_matching import check_flag_evaluation_query_is_ok
from posthog.models.feature_flag.flag_status import FeatureFlagStatus, FeatureFlagStatusChecker
from posthog.models.feature_flag.local_evaluation import (
    DATABASE_FOR_LOCAL_EVALUATION,
    _get_flag_properties_from_filters,
    get_flags_response_for_local_evaluation,
)
from posthog.models.feature_flag.types import PropertyFilterType
from posthog.models.property import Property
from posthog.models.signals import model_activity_signal
from posthog.models.surveys.survey import Survey
from posthog.permissions import ProjectSecretAPITokenPermission
from posthog.queries.base import determine_parsed_date_for_property_matching
from posthog.rate_limit import BurstRateThrottle
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.settings.feature_flags import LOCAL_EVAL_RATE_LIMITS, REMOTE_CONFIG_RATE_LIMITS

logger = logging.getLogger(__name__)

BEHAVIOURAL_COHORT_FOUND_ERROR_CODE = "behavioral_cohort_found"

MAX_PROPERTY_VALUES = 1000


class LocalEvaluationThrottle(BurstRateThrottle):
    # Throttle class that's scoped just to the local evaluation endpoint.
    # This makes the rate limit independent of other endpoints.
    scope = "feature_flag_evaluations"
    rate = "600/minute"

    def allow_request(self, request, view):
        logger = logging.getLogger(__name__)

        team_id = self.safely_get_team_id_from_view(view)
        if team_id:
            try:
                custom_rate = LOCAL_EVAL_RATE_LIMITS.get(team_id)
                if custom_rate:
                    self.rate = custom_rate
                    self.num_requests, self.duration = self.parse_rate(self.rate)
            except Exception:
                logger.exception(f"Error getting team-specific rate limit for team {team_id}")

        return super().allow_request(request, view)


class RemoteConfigThrottle(BurstRateThrottle):
    scope = "feature_flag_remote_config"
    rate = "600/minute"

    def allow_request(self, request, view):
        logger = logging.getLogger(__name__)

        team_id = self.safely_get_team_id_from_view(view)
        if team_id:
            try:
                custom_rate = REMOTE_CONFIG_RATE_LIMITS.get(team_id)
                if custom_rate:
                    self.rate = custom_rate
                    self.num_requests, self.duration = self.parse_rate(self.rate)
            except Exception:
                logger.exception(f"Error getting team-specific rate limit for team {team_id}")

        return super().allow_request(request, view)


class EvaluationTagSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that handles evaluation tags for feature flags.
    Evaluation tags mark which organizational tags also serve as runtime evaluation constraints.

    Note: SDK clients must send 'evaluation_environments' in their flag evaluation requests
    for these constraints to take effect. Without this parameter, all flags are evaluated
    regardless of their evaluation tags.
    """

    evaluation_tags = serializers.ListField(required=False, write_only=True)

    def validate(self, attrs):
        """Validate that evaluation_tags are a subset of tags.

        This ensures that evaluation tags (which control runtime evaluation)
        are always a subset of organizational tags. This maintains the conceptual
        model where evaluation tags are tags that ALSO serve as constraints.
        """
        attrs = super().validate(attrs)

        # Only validate if we have initial_data (not during partial updates without these fields)
        if not hasattr(self, "initial_data"):
            return attrs

        # Get evaluation_tags from the request
        evaluation_tags = self.initial_data.get("evaluation_tags")

        # Only validate if evaluation_tags are provided and non-empty
        # Note: evaluation_tags=[] is valid (clears all evaluation tags)
        if evaluation_tags is not None and evaluation_tags:
            from posthog.api.tagged_item import tagify

            # Get tags from initial_data, defaulting to empty list if not provided
            # Important: We validate against the raw request data, not processed attrs,
            # because TaggedItemSerializerMixin handles tags separately
            tags = self.initial_data.get("tags", [])

            # Normalize both lists using tagify for consistent comparison
            # tagify handles case normalization and special characters
            # NB: this _does_ make flag updates more expensive whenever we update flags with tags.
            # It's a small use case, but wanted to call it out as a potential (but unlikely bottleneck)
            normalized_tags = {tagify(t) for t in tags or []}
            normalized_eval_tags = {tagify(t) for t in evaluation_tags}

            # Evaluation tags must be a subset of organizational tags
            invalid_tags = normalized_eval_tags - normalized_tags
            if invalid_tags:
                raise serializers.ValidationError(
                    f"Evaluation tags must be a subset of tags. Invalid evaluation tags: {', '.join(sorted(invalid_tags))}"
                )

        return attrs

    def _attempt_set_evaluation_tags(self, evaluation_tags, obj):
        """Update evaluation tags for a feature flag using efficient diff logic.

        Instead of deleting all tags and recreating them (which causes unnecessary
        DB operations and activity logs), we calculate the diff and only modify
        what has actually changed.
        """
        if not obj or evaluation_tags is None:
            return

        # Normalize and dedupe tags (same as TaggedItemSerializerMixin does)
        # evaluation_tags=[] is valid and means "clear all evaluation tags"
        deduped_tags = list({tagify(t) for t in evaluation_tags or []})

        # Get current evaluation tags from the database
        # We fetch the tag names directly to avoid loading full objects
        current_eval_tags = set(
            FeatureFlagEvaluationTag.objects.filter(feature_flag=obj)
            .select_related("tag")
            .values_list("tag__name", flat=True)
        )

        # Calculate the diff: what needs to be added vs removed
        # This minimizes database operations and activity log noise
        deduped_tags_set = set(deduped_tags)
        tags_to_add = deduped_tags_set - current_eval_tags
        tags_to_remove = current_eval_tags - deduped_tags_set

        # Remove evaluation tags that are no longer needed
        if tags_to_remove:
            FeatureFlagEvaluationTag.objects.filter(feature_flag=obj, tag__name__in=tags_to_remove).delete()

        # Add new evaluation tags
        if tags_to_add:
            # Create tags if they don't exist (matching TaggedItemSerializerMixin behavior)
            # Note: Our validation ensures these are subset of organizational tags,
            # but we still create them here for consistency with TaggedItemSerializerMixin
            for tag_name in tags_to_add:
                tag, _ = Tag.objects.get_or_create(name=tag_name, team_id=obj.team_id)
                FeatureFlagEvaluationTag.objects.create(feature_flag=obj, tag=tag)

        # Only invalidate cache if there were actual changes
        # This avoids unnecessary cache churn on no-op updates
        if tags_to_add or tags_to_remove:
            try:
                set_feature_flags_for_team_in_cache(obj.team.project_id)
            except Exception as e:
                capture_exception(e)
                pass  # Don't fail if cache invalidation fails

    def to_representation(self, obj):
        ret = super().to_representation(obj)

        # Include evaluation tags in the serialized output
        if hasattr(obj, "evaluation_tags"):
            # Django's prefetch_related creates a cache in _prefetched_objects_cache.
            # If the viewset used prefetch_related (which it should for performance),
            # we can access the tags without hitting the database again.
            if hasattr(obj, "_prefetched_objects_cache") and "evaluation_tags" in obj._prefetched_objects_cache:
                # Use prefetched data (already in memory) - no DB query
                ret["evaluation_tags"] = [et.tag.name for et in obj.evaluation_tags.all()]
            else:
                # Fallback to database query with select_related to minimize queries
                # This should rarely happen as the viewset prefetches evaluation_tags
                ret["evaluation_tags"] = [et.tag.name for et in obj.evaluation_tags.select_related("tag").all()]
        else:
            ret["evaluation_tags"] = []
        return ret


class FeatureFlagSerializer(
    TaggedItemSerializerMixin,
    EvaluationTagSerializerMixin,
    UserAccessControlSerializerMixin,
    serializers.HyperlinkedModelSerializer,
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
    _should_create_usage_dashboard = serializers.BooleanField(required=False, write_only=True, default=True)

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
            "updated_at",
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
            "evaluation_tags",
            "usage_dashboard",
            "analytics_dashboards",
            "has_enriched_analytics",
            "user_access_level",
            "creation_context",
            "is_remote_configuration",
            "has_encrypted_payloads",
            "status",
            "evaluation_runtime",
            "_create_in_folder",
            "_should_create_usage_dashboard",
        ]

    def get_can_edit(self, feature_flag: FeatureFlag) -> bool:
        from typing import cast

        from posthog.rbac.user_access_control import AccessControlLevel, access_level_satisfied_for_resource

        user_access_level = self.get_user_access_level(feature_flag)
        return bool(
            user_access_level
            and access_level_satisfied_for_resource(
                "feature_flag", cast(AccessControlLevel, user_access_level), "editor"
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
            is_valid = properties_all_match(lambda prop: prop.type in ["person", "cohort", "flag"])
            if not is_valid:
                raise serializers.ValidationError(
                    "Filters are not valid (can only use person, cohort, and flag properties)"
                )

            # Validate that flag properties use the correct operator
            flag_props_valid = properties_all_match(
                lambda prop: prop.type != "flag" or prop.operator == PropertyOperator.FLAG_EVALUATES_TO
            )
            if not flag_props_valid:
                raise serializers.ValidationError("Flag properties must use the 'flag_evaluates_to' operator")

            # Check for circular dependencies in flag filters
            self._check_flag_circular_dependencies(filters)
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
                        dependency_cohorts = get_all_cohort_dependencies(initial_cohort)
                        for cohort in [initial_cohort, *dependency_cohorts]:
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

    def _validate_flag_reference(self, flag_reference):
        """Validate and convert flag reference to flag key."""
        from posthog.utils import safe_int

        flag_id = safe_int(flag_reference)
        if flag_id is None:
            raise serializers.ValidationError(
                f"Flag dependencies must reference flag IDs (integers), not flag keys. "
                f"Invalid reference: '{flag_reference}'"
            )

        try:
            flag = FeatureFlag.objects.get(id=flag_id, team__project_id=self.context["project_id"], deleted=False)
            return flag.key
        except FeatureFlag.DoesNotExist:
            raise serializers.ValidationError(f"Flag dependency references non-existent flag with ID {flag_id}")

    def _get_properties_from_filters(self, filters: dict, property_type: PropertyFilterType | None = None):
        """
        Extract properties from filters by iterating through groups.

        Args:
            filters: The filters dictionary containing groups
            property_type: Optional filter by property type (e.g., 'flag', 'cohort')

        Yields:
            Property dictionaries matching the criteria
        """
        for group in filters.get("groups", []):
            for prop in group.get("properties", []):
                if property_type is None or prop.get("type") == property_type:
                    yield prop

    def _get_cohort_properties_from_filters(self, filters: dict):
        """Extract cohort properties from filters."""
        return list(self._get_properties_from_filters(filters, PropertyFilterType.COHORT))

    def _extract_flag_dependencies(self, filters):
        """Extract flag dependencies from filters."""
        dependencies = set()
        for flag_prop in _get_flag_properties_from_filters(filters):
            flag_reference = flag_prop.get("key")
            if flag_reference:
                flag_key = self._validate_flag_reference(flag_reference)
                dependencies.add(flag_key)
        return dependencies

    def _check_flag_circular_dependencies(self, filters):
        """Check for circular dependencies in feature flag conditions."""

        current_flag_key = getattr(self.instance, "key", None) if self.instance else self.initial_data.get("key")
        if not current_flag_key:
            return

        flag_dependencies = self._extract_flag_dependencies(filters)
        if not flag_dependencies:
            return

        # Check for self-reference
        if current_flag_key in flag_dependencies:
            raise serializers.ValidationError(f"Feature flag '{current_flag_key}' cannot depend on itself")

        # Check for cycles using DFS
        def has_cycle(flag_key, path):
            if flag_key in path:
                cycle_path = path[path.index(flag_key) :] + [flag_key]
                cycle_display = " → ".join(cycle_path)
                raise serializers.ValidationError(f"Circular dependency detected: {cycle_display}")

            try:
                flag = FeatureFlag.objects.get(key=flag_key, team__project_id=self.context["project_id"], deleted=False)
                flag_deps = self._extract_flag_dependencies(flag.filters or {})
                for dep_key in flag_deps:
                    has_cycle(dep_key, [*path, flag_key])
            except FeatureFlag.DoesNotExist:
                return  # Non-existent flags have no dependencies

        # Check each dependency for cycles
        for dep_flag_key in flag_dependencies:
            has_cycle(dep_flag_key, [current_flag_key])

    def check_flag_evaluation(self, data):
        # TODO: Once we move to no DB level evaluation, can get rid of this.

        temporary_flag = FeatureFlag(**data)
        project_id = self.context["project_id"]

        # Skip validation for flags with flag dependencies since the evaluation
        # engine doesn't support flag dependencies yet
        filters = data.get("filters", {})
        flag_dependencies = self._extract_flag_dependencies(filters)
        if flag_dependencies:
            return  # Skip validation for flag dependencies

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
        evaluation_tags = validated_data.pop("evaluation_tags", None)  # evaluation tags are created separately
        creation_context = validated_data.pop(
            "creation_context", "feature_flags"
        )  # default to "feature_flags" if an alternative value is not provided

        should_create_usage_dashboard = validated_data.pop("_should_create_usage_dashboard")
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
        self._attempt_set_evaluation_tags(evaluation_tags, instance)

        if should_create_usage_dashboard:
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
        # Prevent DRF from attempting to set reverse FK relation directly
        # We manage evaluation tags via _attempt_set_evaluation_tags below
        validated_data.pop("evaluation_tags", None)

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

            # Check for other flags that depend on this flag
            dependent_flags = self._find_dependent_flags(instance)
            if dependent_flags:
                dependent_flag_names = [f"{flag.key} (ID: {flag.id})" for flag in dependent_flags[:5]]
                if len(dependent_flags) > 5:
                    dependent_flag_names.append(f"and {len(dependent_flags) - 5} more")
                raise exceptions.ValidationError(
                    f"Cannot delete this feature flag because other flags depend on it: {', '.join(dependent_flag_names)}. "
                    f"Please update or delete the dependent flags first."
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

        # Handle evaluation tags (uses initial_data like TaggedItemSerializerMixin does)
        self._attempt_set_evaluation_tags(self.initial_data.get("evaluation_tags"), instance)

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

    def _find_dependent_flags(self, flag_to_delete: FeatureFlag) -> list[FeatureFlag]:
        """Find all active flags that depend on the given flag."""
        return list(
            FeatureFlag.objects.filter(team=flag_to_delete.team, deleted=False, active=True)
            .exclude(id=flag_to_delete.id)
            .extra(
                where=[
                    """
                    EXISTS (
                        SELECT 1 FROM jsonb_array_elements(filters->'groups') AS grp
                        CROSS JOIN jsonb_array_elements(grp->'properties') AS prop
                        WHERE prop->>'type' = 'flag'
                        AND prop->>'key' = %s
                    )
                    """
                ],
                params=[str(flag_to_delete.id)],
            )
            .order_by("key")
        )

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

        # Get all cohort IDs used in the feature flag
        cohort_ids = set()
        for cohort_prop in self._get_cohort_properties_from_filters(filters):
            value = cohort_prop.get("value")
            # Ensure we only add valid integer cohort IDs
            if value is not None:
                if isinstance(value, list):
                    for v in value:
                        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                            cohort_ids.add(int(v) if isinstance(v, str) else v)
                elif isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                    cohort_ids.add(int(value) if isinstance(value, str) else value)

        # Use prefetched cohorts if available
        if hasattr(instance.team, "available_cohorts"):
            cohorts = {
                str(cohort.id): cohort.name for cohort in instance.team.available_cohorts if cohort.id in cohort_ids
            }
        else:
            # Fallback to database query if cohorts weren't prefetched
            # Only query if we have valid integer IDs
            if cohort_ids:
                cohorts = {
                    str(cohort.id): cohort.name
                    for cohort in Cohort.objects.filter(id__in=cohort_ids, team__project_id=self.context["project_id"])
                }
            else:
                cohorts = {}

        # Add cohort names to the response
        for cohort_prop in self._get_cohort_properties_from_filters(filters):
            cohort_prop["cohort_name"] = cohorts.get(str(cohort_prop.get("value")))

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
    evaluation_tags = serializers.SerializerMethodField()

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
            "evaluation_runtime",
            "evaluation_tags",
        ]

    def get_evaluation_tags(self, feature_flag: FeatureFlag) -> list[str]:
        # Prefer cached/provided names; fallback to relation.
        try:
            names = getattr(feature_flag, "evaluation_tag_names", None)
            if names is None:
                names = [et.tag.name for et in feature_flag.evaluation_tags.select_related("tag").all()]
            return names or []
        except Exception:
            return []


class LaunchDarklyRateLimiter:
    """Handles LaunchDarkly API rate limiting with exponential backoff and jitter"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def make_request_with_rate_limiting(self, url: str, headers: dict, timeout: int = 30, max_retries: int = 3):
        """
        Make a request with proper rate limiting and exponential backoff.

        Returns:
            tuple: (response, success) where response is the requests.Response object
                   and success is a boolean indicating if the request was successful
        """
        import requests

        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=timeout)

                # Log rate limit headers for monitoring
                self._log_rate_limit_headers(response, url)

                if response.status_code == 429:
                    # Rate limited - implement exponential backoff with jitter
                    wait_time = self._calculate_backoff_time(attempt, response)
                    self.logger.warning(
                        f"Rate limited on {url}, attempt {attempt + 1}/{max_retries}, waiting {wait_time:.2f}s"
                    )

                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        time.sleep(wait_time)
                        continue
                    else:
                        self.logger.error(f"Max retries reached for {url}, returning 429 response")
                        return response, False

                elif response.status_code in [200, 401, 403, 404]:
                    # Success or expected error codes
                    return response, True

                else:
                    # Unexpected error
                    self.logger.warning(f"Unexpected status code {response.status_code} for {url}")
                    return response, False

            except Exception as e:
                self.logger.exception(f"Request failed for {url}, attempt {attempt + 1}/{max_retries}: {str(e)}")
                if attempt == max_retries - 1:
                    raise

                # Wait before retrying on exception
                wait_time = self._calculate_backoff_time(attempt)
                time.sleep(wait_time)

        # Should not reach here
        raise Exception(f"Failed to complete request to {url} after {max_retries} attempts")

    def _log_rate_limit_headers(self, response, url: str):
        """Log rate limit headers for monitoring and debugging"""
        global_remaining = response.headers.get("X-Ratelimit-Global-Remaining")
        route_remaining = response.headers.get("X-Ratelimit-Route-Remaining")
        reset_time = response.headers.get("X-Ratelimit-Reset")
        retry_after = response.headers.get("Retry-After")

        if any([global_remaining, route_remaining, reset_time]):
            self.logger.info(
                f"Rate limit status for {url}: "
                f"global_remaining={global_remaining}, "
                f"route_remaining={route_remaining}, "
                f"reset_time={reset_time}, "
                f"retry_after={retry_after}"
            )

    def _calculate_backoff_time(self, attempt: int, response=None) -> float:
        """
        Calculate backoff time using exponential backoff with jitter.

        Args:
            attempt: The attempt number (0-based)
            response: Optional response object to check for Retry-After header

        Returns:
            float: Time to wait in seconds
        """
        # Check for Retry-After header first (LaunchDarkly recommendation)
        if response and response.headers.get("Retry-After"):
            try:
                retry_after = int(response.headers["Retry-After"])
                # Add small jitter to avoid thundering herd
                jitter = random.uniform(0.1, 0.5)
                return retry_after + jitter
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid Retry-After header: {response.headers.get('Retry-After')}")

        # Exponential backoff: base_delay * (2 ^ attempt) + jitter
        base_delay = 1.0  # 1 second base delay
        exponential_delay = base_delay * (2**attempt)

        # Cap the delay at 60 seconds
        exponential_delay = min(exponential_delay, 60.0)

        # Add jitter (10-50% of the delay) to avoid thundering herd
        jitter = random.uniform(0.1 * exponential_delay, 0.5 * exponential_delay)

        return exponential_delay + jitter


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
    authentication_classes = [
        TemporaryTokenAuthentication,  # Allows endpoint to be called from the Toolbar
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rate_limiter = LaunchDarklyRateLimiter()

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "active":
                if filters[key] == "STALE":
                    # Get flags that are at least 30 days old and active
                    # This is an approximation - the serializer will compute the exact status
                    queryset = queryset.filter(active=True, created_at__lt=thirty_days_ago()).extra(
                        where=[
                            """
                            (
                                (
                                    EXISTS (
                                        SELECT 1 FROM jsonb_array_elements(filters->'groups') AS elem
                                        WHERE elem->>'rollout_percentage' = '100'
                                        AND (elem->'properties')::text = '[]'::text
                                    )
                                    AND (filters->'multivariate' IS NULL OR jsonb_array_length(filters->'multivariate'->'variants') = 0)
                                )
                                OR
                                (
                                    EXISTS (
                                        SELECT 1 FROM jsonb_array_elements(filters->'multivariate'->'variants') AS variant
                                        WHERE variant->>'rollout_percentage' = '100'
                                    )
                                    AND EXISTS (
                                        SELECT 1 FROM jsonb_array_elements(filters->'groups') AS elem
                                        WHERE elem->>'rollout_percentage' = '100'
                                        AND (elem->'properties')::text = '[]'::text
                                    )
                                )
                            )
                            """
                        ]
                    )
                else:
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
            elif key == "evaluation_runtime":
                evaluation_runtime = request.GET["evaluation_runtime"]
                queryset = queryset.filter(evaluation_runtime=evaluation_runtime)
            elif key == "excluded_properties":
                import json

                try:
                    excluded_keys = json.loads(request.GET["excluded_properties"])
                    if excluded_keys:
                        queryset = queryset.exclude(key__in=excluded_keys)
                except (json.JSONDecodeError, TypeError):
                    # If the JSON is invalid, ignore the filter
                    pass

        return queryset

    def safely_get_queryset(self, queryset) -> QuerySet:
        from posthog.models.feature_flag import FeatureFlagEvaluationTag

        # Always prefetch experiment_set since it's used in both list and retrieve
        queryset = queryset.prefetch_related(
            Prefetch("experiment_set", queryset=Experiment.objects.filter(deleted=False), to_attr="_active_experiments")
        )

        # Prefetch evaluation tags to avoid N+1 queries when serializing.
        # Without this, each flag would trigger a separate query to fetch its
        # evaluation tags. With prefetch_related, Django loads all evaluation
        # tags in a single query and caches them on the model instances.
        queryset = queryset.prefetch_related(
            Prefetch(
                "evaluation_tags",
                queryset=FeatureFlagEvaluationTag.objects.select_related("tag"),
            )
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
                enum=["true", "false", "STALE"],
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
            OpenApiParameter(
                "evaluation_runtime",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["server", "client", "both"],
                description="Filter feature flags by their evaluation runtime.",
            ),
            OpenApiParameter(
                "excluded_properties",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="JSON-encoded list of feature flag keys to exclude from the results.",
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

    @action(methods=["POST"], detail=False)
    def bulk_keys(self, request: request.Request, **kwargs):
        """
        Get feature flag keys by IDs.
        Accepts a list of feature flag IDs and returns a mapping of ID to key.
        """
        flag_ids = request.data.get("ids", [])

        if not flag_ids:
            return Response({"keys": {}})

        # Convert to integers and track invalid IDs
        validated_ids = []
        invalid_ids = []
        for flag_id in flag_ids:
            if str(flag_id).isdigit():
                try:
                    validated_ids.append(int(flag_id))
                except (ValueError, TypeError):
                    invalid_ids.append(flag_id)
            else:
                invalid_ids.append(flag_id)

        # If no valid IDs were provided, return error
        if not validated_ids and flag_ids:
            return Response({"error": "Invalid flag IDs provided"}, status=status.HTTP_400_BAD_REQUEST)

        if not validated_ids:
            return Response({"keys": {}})

        flag_ids = validated_ids

        # Prepare response data
        response_data: dict[str, Any] = {"keys": {}}

        # Add warning if there were invalid IDs
        if invalid_ids:
            response_data["warning"] = f"Invalid flag IDs ignored: {invalid_ids}"

        # Fetch flags by IDs
        flags = FeatureFlag.objects.filter(
            id__in=flag_ids, team__project_id=self.project_id, deleted=False
        ).values_list("id", "key")

        # Create mapping of ID to key
        keys_mapping = {str(flag_id): key for flag_id, key in flags}
        response_data["keys"] = keys_mapping

        return Response(response_data)

    @action(
        methods=["GET"],
        detail=False,
        throttle_classes=[LocalEvaluationThrottle],
        required_scopes=["feature_flag:read"],
        authentication_classes=[TemporaryTokenAuthentication, ProjectSecretAPIKeyAuthentication],
        permission_classes=[ProjectSecretAPITokenPermission],
    )
    def local_evaluation(self, request: request.Request, **kwargs) -> Response:
        # **kwargs is required because DRF passes parent_lookup_project_id from nested router
        start_time = time.time()
        logger = logging.getLogger(__name__)

        include_cohorts = "send_cohorts" in request.GET

        # Track send_cohorts parameter usage
        statsd.incr("posthog_local_evaluation_request", tags={"send_cohorts": str(include_cohorts).lower()})

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
                    "has_send_cohorts": include_cohorts,
                },
            )
            response_data = get_flags_response_for_local_evaluation(self.team, include_cohorts)

            if not response_data:
                raise Exception("No response data")

            flag_keys = [flag["key"] for flag in response_data["flags"]]

            # Add request for analytics
            if len(flag_keys) > 0 and not all(
                flag_key.startswith(SURVEY_TARGETING_FLAG_PREFIX) for flag_key in flag_keys
            ):
                increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

            return Response(response_data)

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

    def _handle_cached_response(self, cached_response: Optional[dict]) -> Optional[Response]:
        """Handle cached response including analytics tracking."""
        if cached_response is None:
            return None

        # Increment request count for analytics (exclude survey targeting flags)
        if cached_response.get("flags") and not all(
            flag.get("key", "").startswith(SURVEY_TARGETING_FLAG_PREFIX) for flag in cached_response["flags"]
        ):
            increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

        return Response(cached_response)

    def _build_cohort_properties_cache(self, cohorts, seen_cohorts_cache, feature_flag):
        """
        Builds a cache of cohort properties for a feature flag.

        This is used to avoid duplicate queries for cohort properties.

        Args:
            cohorts: The cache of cohort properties.
            seen_cohorts_cache: The cache of seen cohorts.
            feature_flag: The feature flag to build the cache for.
        """
        logger = logging.getLogger(__name__)
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
        throttle_classes=[RemoteConfigThrottle],
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

    @action(methods=["POST"], detail=False)
    def fetch_external_flags(self, request: request.Request, **kwargs):
        """
        Fetch feature flags from external providers for migration.
        """
        provider = request.data.get("provider")
        api_key = request.data.get("api_key")
        environment = request.data.get("environment", "production")  # Default to production

        if not provider or not api_key:
            return Response({"error": "Provider and API key are required"}, status=400)

        if provider not in ["launchdarkly"]:
            return Response(
                {"error": f"Provider {provider} is not supported. Supported providers: launchdarkly"}, status=400
            )

        try:
            # Fetch flags from LaunchDarkly
            project_key = request.data.get("project_key", "default")
            external_flags = self._fetch_launchdarkly_flags(api_key, project_key)

            if isinstance(external_flags, Response):
                return external_flags  # Error response

            # Add debugging for the problematic flag in the raw API response
            for flag in external_flags:
                if flag.get("key") == "flag-with-cohort":
                    logger.error(f"DEBUG API RESPONSE flag-with-cohort: Full flag data: {flag}")
                    break

            # Transform flags to our standard format
            logger.info(f"LaunchDarkly: Transforming {len(external_flags)} flags for response")
            transformed_flags = []
            for idx, flag in enumerate(external_flags):
                flag_key = flag.get("key", "no-key")
                try:
                    transformed_flag = self._transform_launchdarkly_flag_for_response(
                        flag, environment, api_key, project_key
                    )
                    transformed_flags.append(transformed_flag)
                    logger.info(
                        f"LaunchDarkly: Transformed flag {idx + 1}/{len(external_flags)}: {flag_key} - importable: {transformed_flag['importable']}"
                    )
                except Exception as e:
                    logger.exception(
                        f"LaunchDarkly: Failed to transform flag {idx + 1}/{len(external_flags)}: {flag_key} - Error: {str(e)}"
                    )

            logger.info(
                f"LaunchDarkly: Successfully transformed {len(transformed_flags)} out of {len(external_flags)} flags"
            )

            importable_flags = [flag for flag in transformed_flags if flag["importable"]]
            non_importable_flags = [flag for flag in transformed_flags if not flag["importable"]]

            logger.info(
                f"LaunchDarkly: Final counts - importable: {len(importable_flags)}, non-importable: {len(non_importable_flags)}, total: {len(transformed_flags)}"
            )

            return Response(
                {
                    "importable_flags": importable_flags,
                    "non_importable_flags": non_importable_flags,
                    "total_flags": len(transformed_flags),
                    "importable_count": len(importable_flags),
                    "non_importable_count": len(non_importable_flags),
                }
            )

        except Exception as e:
            return Response({"error": f"Failed to fetch flags from {provider}: {str(e)}"}, status=500)

    @action(methods=["POST"], detail=False)
    def import_external_flags(self, request: request.Request, **kwargs):
        """
        Import selected feature flags from external providers to PostHog.
        Only flags with manual percentage rules are supported.
        """
        provider = request.data.get("provider")
        selected_flags = request.data.get("selected_flags", [])
        environment = request.data.get("environment", "production")

        if not provider or not selected_flags:
            return Response({"error": "Provider and selected flags are required"}, status=400)

        if provider not in ["amplitude", "launchdarkly"]:
            return Response({"error": f"Provider {provider} is not supported"}, status=400)

        imported_flags = []
        failed_imports = []

        for flag_data in selected_flags:
            try:
                # Validate flag is importable (only manual percentage rules)
                # Use the raw environments data for validation if available
                raw_environments = flag_data.get("metadata", {}).get("raw_environments")
                if raw_environments and provider == "launchdarkly":
                    # Create a minimal flag object for validation
                    mock_flag = {"key": flag_data.get("key", ""), "environments": raw_environments}
                    if not self._check_launchdarkly_flag_importable(mock_flag, environment):
                        failed_imports.append(
                            {"flag": flag_data, "error": f"Flag is not importable for environment '{environment}'"}
                        )
                        continue
                elif not self._is_flag_importable_for_creation(flag_data):
                    failed_imports.append(
                        {"flag": flag_data, "error": "Only flags with manual percentage rollout rules are supported"}
                    )
                    continue

                # Check for conflicts with existing flags
                flag_key = flag_data.get("key", "")
                existing_flag = FeatureFlag.objects.filter(team=self.team, key=flag_key, deleted=False).first()

                if existing_flag:
                    failed_imports.append({"flag": flag_data, "error": f"Flag with key '{flag_key}' already exists"})
                    continue

                # Convert to PostHog format and create flag
                posthog_flag_data = self._convert_external_flag_to_posthog_format(flag_data, provider, environment)

                new_flag = FeatureFlag.objects.create(
                    team=self.team, created_by=request.user, last_modified_by=request.user, **posthog_flag_data
                )

                imported_flags.append(
                    {
                        "external_flag": flag_data,
                        "posthog_flag": {
                            "id": new_flag.id,
                            "key": new_flag.key,
                            "name": new_flag.name,
                            "active": new_flag.active,
                        },
                    }
                )

            except Exception as e:
                failed_imports.append({"flag": flag_data, "error": f"Failed to import flag: {str(e)}"})

        return Response(
            {
                "imported_flags": imported_flags,
                "failed_imports": failed_imports,
                "success_count": len(imported_flags),
                "failure_count": len(failed_imports),
            }
        )

    def _is_flag_importable_for_creation(self, flag_data):
        """Check if a flag can be imported (only manual percentage rules allowed)"""
        conditions = flag_data.get("conditions", [])

        # Must have exactly one condition
        if len(conditions) != 1:
            return False

        condition = conditions[0]

        # Must have empty properties (no targeting rules)
        if condition.get("properties") and len(condition["properties"]) > 0:
            return False

        # Must have a rollout percentage (manual percentage rule)
        if "rollout_percentage" not in condition:
            return False

        return True

    def _extract_launchdarkly_production_config(self, raw_flag, environment="production"):
        """Extract enabled state and rollout percentage from LaunchDarkly specified environment"""
        environments = raw_flag.get("environments", {})

        # Try specified environment first, then fall back to any enabled environment
        target_env = None
        if environment in environments:
            target_env = environments[environment]
        else:
            # Fallback to first enabled environment
            for _env_name, env_data in environments.items():
                if env_data.get("on", False):
                    target_env = env_data
                    break

        if not target_env:
            return False, 0  # No enabled environments

        enabled = target_env.get("on", False)

        # Extract rollout percentage from fallthrough
        fallthrough = target_env.get("fallthrough", {})
        rollout_percentage = 100  # Default to 100%

        if fallthrough.get("rollout"):
            # Has rollout configuration
            rollout = fallthrough["rollout"]
            variations = rollout.get("variations", [])

            # Calculate percentage for "true" variation (usually variation 0 or 1)
            total_weight = sum(v.get("weight", 0) for v in variations)
            if total_weight > 0:
                # Find the "true" variation - usually the one that's not the "off" variation
                off_variation = target_env.get("offVariation", 0)
                for variation in variations:
                    variation_index = variation.get("variation")
                    if variation_index != off_variation:
                        weight = variation.get("weight", 0)
                        rollout_percentage = int((weight / total_weight) * 100)
                        break
        elif fallthrough.get("variation") is not None:
            # Direct variation assignment
            variation_index = fallthrough.get("variation")
            off_variation = target_env.get("offVariation", 0)

            if variation_index == off_variation:
                rollout_percentage = 0  # Flag is off
            else:
                rollout_percentage = 100  # Flag is fully on

        return enabled, rollout_percentage

    def _extract_launchdarkly_variant_rollouts(self, raw_flag, transformed_variants, environment="production"):
        """Extract variant rollout percentages from LaunchDarkly specified environment"""
        environments = raw_flag.get("environments", {})
        flag_key = raw_flag.get("key", "unknown")

        logger.debug(f"Flag {flag_key}: Starting variant extraction for environment {environment}")
        logger.debug(f"Flag {flag_key}: Environments: {list(environments.keys())}")
        logger.debug(f"Flag {flag_key}: Transformed variants: {[v.get('key') for v in transformed_variants]}")

        # Get specified environment or fallback to first enabled environment
        target_env = None
        if environment in environments:
            target_env = environments[environment]
            logger.debug(f"Flag {flag_key}: Using {environment} environment")
        else:
            for env_name, env_data in environments.items():
                if env_data.get("on", False):
                    target_env = env_data
                    logger.debug(f"Flag {flag_key}: Using fallback environment: {env_name}")
                    break

        if not target_env:
            logger.debug(f"Flag {flag_key}: No enabled environment found")
            return {}

        # Extract variant rollouts from rules or fallthrough configuration
        rules = target_env.get("rules", [])
        fallthrough = target_env.get("fallthrough", {})
        variant_rollouts = {}

        logger.debug(f"Flag {flag_key}: Fallthrough: {fallthrough}")

        # First, check rules for rollout with variations
        rollout_found = False
        for _rule_idx, rule in enumerate(rules):
            if rule.get("rollout") and rule["rollout"].get("variations"):
                rollout = rule["rollout"]
                variations = rollout["variations"]
                total_weight = sum(v.get("weight", 0) for v in variations)

                logger.debug(f"Flag {flag_key}: Rule rollout variations: {variations}")
                logger.debug(f"Flag {flag_key}: Total weight: {total_weight}")

                if total_weight > 0:
                    # Map rollout variations to transformed variants by variation index
                    for variation_config in variations:
                        variation_index = variation_config.get("variation")
                        weight = variation_config.get("weight", 0)
                        percentage = int((weight / total_weight) * 100)

                        logger.debug(
                            f"Flag {flag_key}: Processing variation {variation_index}, weight: {weight}, percentage: {percentage}"
                        )

                        # Map variation index to corresponding transformed variant
                        if variation_index is not None and variation_index < len(transformed_variants):
                            variant = transformed_variants[variation_index]
                            variant_key = variant.get("key", f"variant_{variation_index}")
                            variant_value = variant.get("value")

                            logger.debug(
                                f"Flag {flag_key}: Mapping variation {variation_index} -> variant {variant_key}"
                            )

                            # Skip boolean variants (true/false)
                            if variant_value not in [True, False, "true", "false"]:
                                variant_rollouts[variant_key] = percentage
                                logger.debug(f"Flag {flag_key}: Added variant {variant_key} with {percentage}%")
                            else:
                                logger.debug(f"Flag {flag_key}: Skipped boolean variant {variant_key}")
                        else:
                            logger.debug(
                                f"Flag {flag_key}: Invalid variation index {variation_index} for {len(transformed_variants)} variants"
                            )

                    rollout_found = True
                    break  # Use the first rule with rollout

        # If no rollout found in rules, check fallthrough
        if not rollout_found and fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
            rollout = fallthrough["rollout"]
            variations = rollout["variations"]
            total_weight = sum(v.get("weight", 0) for v in variations)

            logger.debug(f"Flag {flag_key}: Rollout variations: {variations}")
            logger.debug(f"Flag {flag_key}: Total weight: {total_weight}")

            if total_weight > 0:
                # Map rollout variations to transformed variants by variation index
                for variation_config in variations:
                    variation_index = variation_config.get("variation")
                    weight = variation_config.get("weight", 0)
                    percentage = int((weight / total_weight) * 100)

                    logger.debug(
                        f"Flag {flag_key}: Processing variation {variation_index}, weight: {weight}, percentage: {percentage}"
                    )

                    # Map variation index to corresponding transformed variant
                    if variation_index is not None and variation_index < len(transformed_variants):
                        variant = transformed_variants[variation_index]
                        variant_key = variant.get("key", f"variant_{variation_index}")
                        variant_value = variant.get("value")

                        logger.debug(f"Flag {flag_key}: Mapping variation {variation_index} -> variant {variant_key}")

                        # Skip boolean variants (true/false)
                        if variant_value not in [True, False, "true", "false"]:
                            variant_rollouts[variant_key] = percentage
                            logger.debug(f"Flag {flag_key}: Added variant {variant_key} with {percentage}%")
                        else:
                            logger.debug(f"Flag {flag_key}: Skipped boolean variant {variant_key}")
                    else:
                        logger.debug(
                            f"Flag {flag_key}: Invalid variation index {variation_index} for {len(transformed_variants)} variants"
                        )
        if not rollout_found:
            logger.debug(f"Flag {flag_key}: No rollout variations found in rules or fallthrough")

        logger.debug(f"Flag {flag_key}: Final variant rollouts: {variant_rollouts}")
        return variant_rollouts

    def _convert_external_flag_to_posthog_format(self, external_flag, provider, environment="production"):
        """Convert external flag to PostHog FeatureFlag model format"""
        key = external_flag.get("key", "")
        name = external_flag.get("name", "") or key

        if "conditions" in external_flag:
            pass

        # Get the actual enabled state and rollout percentage from environment data
        if provider == "launchdarkly":
            # Use raw environments data if available
            raw_environments = external_flag.get("metadata", {}).get("raw_environments")

            if raw_environments:
                # Create a minimal flag object with environments for extraction
                mock_flag = {"key": key, "environments": raw_environments}
                enabled, rollout_percentage = self._extract_launchdarkly_production_config(mock_flag, environment)
            else:
                # Fallback to transformed data
                enabled = external_flag.get("enabled", True)
                conditions = external_flag.get("conditions", [])
                conditions[0].get("rollout_percentage", 100) if conditions else 100
        else:
            enabled = external_flag.get("enabled", True)
            # For other providers, use the conditions data
            conditions = external_flag.get("conditions", [])

        # Handle multivariate flags
        variants = external_flag.get("variants", [])
        has_variants = False

        if variants and len(variants) > 0:
            if provider == "launchdarkly":
                # Get variant rollout percentages from raw environment data
                raw_environments = external_flag.get("metadata", {}).get("raw_environments")
                raw_variations = external_flag.get("metadata", {}).get("raw_variations", [])
                variant_rollouts = {}

                if raw_environments and environment in raw_environments:
                    pass
                logger.debug(f"Flag {key}: Raw environments available: {raw_environments is not None}")
                logger.debug(
                    f"Flag {key}: Raw variations available: {raw_variations is not None and len(raw_variations) > 0}"
                )
                logger.debug(f"Flag {key}: Raw variations: {raw_variations}")

                if raw_environments:
                    mock_flag = {"key": key, "environments": raw_environments}
                    variant_rollouts = self._extract_launchdarkly_variant_rollouts(mock_flag, variants, environment)
                    logger.debug(f"Flag {key}: Extracted variant rollouts: {variant_rollouts}")
                else:
                    logger.debug(f"Flag {key}: Missing raw environments data")

                # Filter out default boolean variants for LaunchDarkly
                non_boolean_variants = []
                logger.debug(f"Flag {key}: Processing variants: {variants}")

                for variant in variants:
                    value = variant.get("value")
                    variant_key = variant.get("key", "")
                    logger.debug(f"Flag {key}: Processing variant {variant_key} with value {value}")

                    if value not in [True, False, "true", "false"]:
                        rollout_pct = variant_rollouts.get(variant_key, 0)
                        logger.debug(f"Flag {key}: Variant {variant_key} gets rollout {rollout_pct}%")

                        non_boolean_variants.append(
                            {
                                "key": variant_key,
                                "name": variant.get("name", ""),
                                "rollout_percentage": rollout_pct,
                            }
                        )
                    else:
                        logger.debug(f"Flag {key}: Skipping boolean variant {variant_key}")

                logger.debug(f"Flag {key}: Final non-boolean variants: {non_boolean_variants}")

                if non_boolean_variants:
                    has_variants = True
                    filters = {"multivariate": {"variants": non_boolean_variants}}
            else:
                # For other providers, include all variants
                posthog_variants = []
                for variant in variants:
                    posthog_variants.append(
                        {
                            "key": variant.get("key", ""),
                            "name": variant.get("name", ""),
                            "rollout_percentage": variant.get("rollout_percentage", 0),
                        }
                    )
                has_variants = True
                filters = {"multivariate": {"variants": posthog_variants}}

        # For LaunchDarkly imports, re-transform conditions with cohort creation
        if provider == "launchdarkly":
            # Get raw flag data for cohort creation
            raw_environments = external_flag.get("metadata", {}).get("raw_environments")
            if raw_environments:
                # Create a mock raw flag for transformation with cohort creation
                mock_raw_flag = {
                    "key": key,
                    "environments": raw_environments,
                    "metadata": external_flag.get("metadata", {}),
                }

                # Use the LaunchDarkly API credentials from the metadata if available
                import_api_key = external_flag.get("metadata", {}).get("api_key")
                import_project_key = external_flag.get("metadata", {}).get("project_key")

                # Re-transform conditions with cohort creation
                conditions = self._transform_launchdarkly_conditions(
                    mock_raw_flag, environment, import_api_key, import_project_key, self.team
                )
            else:
                # Fallback to existing conditions if no raw data
                conditions = external_flag.get("conditions", [])
        else:
            # For other providers, use existing conditions
            conditions = external_flag.get("conditions", [])

        if not has_variants:
            filters = {"groups": [], "payloads": {}, "multivariate": None}

        # Build groups from the transformed conditions
        if conditions:
            if "groups" not in filters:
                filters["groups"] = []

            for condition in conditions:
                group = {
                    "properties": condition.get("properties", []),
                    "rollout_percentage": condition.get("rollout_percentage", 100),
                }

                # For boolean flags (no variants), always set variant to null
                # For multivariate flags, use the condition's variant or null
                if has_variants:
                    if condition.get("variant"):
                        group["variant"] = condition.get("variant")
                    else:
                        group["variant"] = None
                else:
                    group["variant"] = None

                filters["groups"].append(group)
        else:
            # If no conditions exist, the flag is effectively disabled
            # Don't add any groups - empty groups array means flag is off for everyone
            # filters["groups"] remains empty
            pass

        return {
            "key": key,
            "name": name,
            "filters": filters,
            "active": enabled,
            "version": 1,
        }

    def _check_amplitude_flag_importable(self, flag):
        """Check if an Amplitude flag can be imported to PostHog"""
        # Multiple variants beyond on/off not supported
        if flag.get("variants") and len(flag["variants"]) > 2:
            return False

        # Custom bucketing keys not supported
        if flag.get("bucketingKey") and flag["bucketingKey"] != "amplitude_id":
            return False

        # Remote evaluation mode not supported
        if flag.get("evaluationMode") == "remote":
            return False

        return True

    def _transform_amplitude_conditions(self, flag):
        """Transform Amplitude targeting rules to PostHog condition format"""
        rules = flag.get("rules", [])
        if not rules:
            return [{"properties": [], "rollout_percentage": flag.get("rolloutPercentage", 100)}]

        conditions = []
        for rule in rules:
            condition = {
                "properties": [],
                "rollout_percentage": rule.get("rolloutPercentage", rule.get("percentage", 100)),
            }

            if rule.get("variant"):
                condition["variant"] = rule["variant"]

            # Transform rule conditions to properties
            if rule.get("conditions"):
                for amp_condition in rule["conditions"]:
                    prop = {
                        "key": amp_condition.get("prop") or amp_condition.get("property", ""),
                        "operator": self._map_amplitude_operator(
                            amp_condition.get("op") or amp_condition.get("operator", "is")
                        ),
                        "value": (amp_condition.get("values") or [amp_condition.get("value")])[0]
                        if amp_condition.get("values") or amp_condition.get("value")
                        else "",
                        "type": self._infer_property_type(
                            (amp_condition.get("values") or [amp_condition.get("value")])[0]
                            if amp_condition.get("values") or amp_condition.get("value")
                            else ""
                        ),
                    }
                    condition["properties"].append(prop)

            conditions.append(condition)

        return conditions

    def _transform_amplitude_variants(self, flag):
        """Transform Amplitude variants to PostHog format"""
        variants = flag.get("variants", [])
        if not variants or len(variants) <= 2:
            return []

        transformed_variants = []
        for variant in variants:
            transformed_variant = {
                "key": variant.get("key") or variant.get("value", ""),
                "name": variant.get("name") or variant.get("value", ""),
                "rollout_percentage": variant.get("rolloutWeight", variant.get("percentage", 0)),
                "value": variant.get("payload") or variant.get("value"),
            }
            transformed_variants.append(transformed_variant)

        return transformed_variants

    def _map_amplitude_operator(self, amplitude_op):
        """Map Amplitude operators to PostHog operators"""
        operator_map = {
            "is": "equals",
            "is not": "not_equals",
            "contains": "icontains",
            "does not contain": "not_icontains",
            "is set": "is_set",
            "is not set": "is_not_set",
            "greater than": "gt",
            "less than": "lt",
            "greater than or equal": "gte",
            "less than or equal": "lte",
        }
        return operator_map.get(amplitude_op, "equals")

    def _infer_property_type(self, value):
        """Infer property type from value"""
        if isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int | float):
            return "number"
        elif isinstance(value, str) and value:
            try:
                from datetime import datetime

                datetime.fromisoformat(value.replace("Z", "+00:00"))
                return "datetime"
            except:
                pass
        return "string"

    def _transform_launchdarkly_flag(self, flag):
        """Transform LaunchDarkly flag to common format for processing"""
        # Handle case where flag might not be a dict
        if not isinstance(flag, dict):
            return {
                "id": str(flag),
                "key": str(flag),
                "name": str(flag),
                "description": "",
                "enabled": False,
                "createdAt": None,
                "updatedAt": None,
                "variants": [],
                "rules": [],
            }

        # LaunchDarkly flag structure to common format
        transformed = {
            "id": flag.get("key", ""),
            "key": flag.get("key", ""),
            "name": flag.get("name", flag.get("key", "")),
            "description": flag.get("description", ""),
            "enabled": flag.get("on", False),
            "createdAt": flag.get("creationDate"),
            "updatedAt": flag.get("_lastModified"),
            "variants": [],
            "rules": [],
        }

        # Transform variations to variants
        variations = flag.get("variations", [])
        if variations:
            for idx, variation in enumerate(variations):
                # Use variation name as the key (LaunchDarkly variant key)
                variation_value = variation.get("value")
                variation_name = variation.get("name", f"variant_{idx}")
                transformed["variants"].append(
                    {
                        "key": variation_name,
                        "value": variation_value,
                        "name": variation_name,
                        "description": variation.get("description", ""),
                        "rollout_percentage": 0,  # Will be calculated based on targeting rules
                        "is_default": idx == 0,  # First variation is usually the "off" state
                    }
                )

        # Transform targeting rules
        if flag.get("targeting"):
            targeting = flag["targeting"]

            # Process rules
            for rule in targeting.get("rules", []):
                transformed_rule = {
                    "id": rule.get("id"),
                    "clauses": [],
                    "variation": rule.get("variation"),
                    "rollout": rule.get("rollout"),
                }

                # Transform clauses (conditions)
                for clause in rule.get("clauses", []):
                    transformed_rule["clauses"].append(
                        {
                            "attribute": clause.get("attribute"),
                            "op": clause.get("op"),
                            "values": clause.get("values", []),
                            "negate": clause.get("negate", False),
                        }
                    )

                transformed["rules"].append(transformed_rule)

            # Add fallthrough rule if exists
            if targeting.get("fallthrough"):
                transformed["fallthrough"] = targeting["fallthrough"]

        return transformed

    def _is_valid_variant_key(self, variant_key):
        """Check if variant key contains only letters, numbers, hyphens, and underscores"""
        import re

        return bool(re.match(r"^[a-zA-Z0-9_-]+$", variant_key))

    def _check_launchdarkly_flag_importable(self, flag, environment="production"):
        """Check if a LaunchDarkly flag can be imported to PostHog (supports manual percentage and simple rules)"""
        flag_key = flag.get("key", "unknown")

        if not isinstance(flag, dict):
            logger.debug(f"Flag {flag_key} rejected: not a dict")
            return False

        # Rate limited flags cannot be validated properly
        if flag.get("_rate_limited"):
            logger.debug(f"Flag {flag_key} rejected: rate limited")
            return False

        # Prerequisites not supported
        if flag.get("prerequisites") and len(flag["prerequisites"]) > 0:
            logger.debug(f"Flag {flag_key} rejected: has prerequisites")
            return False

        # Progressive rollouts not supported
        if self._has_progressive_rollout(flag, environment):
            logger.debug(f"Flag {flag_key} rejected: progressive rollout pattern detected")
            return False

        # Migration flags not supported (these are infrastructure flags for system migrations)
        if self._is_migration_flag(flag):
            logger.debug(f"Flag {flag_key} rejected: migration flag detected")
            return False

        # Check only the specified environment
        environments = flag.get("environments", {})
        if not environments:
            logger.debug(f"Flag {flag_key} rejected: no environments")
            return False

        # Get the specified environment
        env_data = environments.get(environment)

        if flag_key == "flag-with-cohort":
            logger.error(f"DEBUG VALIDATION {flag_key}: Environment '{environment}' found: {env_data is not None}")

        if not env_data:
            logger.debug(f"Flag {flag_key} rejected: environment '{environment}' not found")
            return False

        # Skip if not enabled
        is_enabled = env_data.get("on", False)

        if flag_key == "flag-with-cohort":
            logger.error(f"DEBUG VALIDATION {flag_key}: Environment '{environment}' enabled: {is_enabled}")

        if not is_enabled:
            logger.debug(f"Flag {flag_key} env {environment}: environment is disabled")
            return False

        logger.debug(f"Flag {flag.get('key', 'unknown')} env {environment}: checking rules")

        rules = env_data.get("rules", [])

        # Check if rules have supported clauses
        for rule_idx, rule in enumerate(rules):
            clauses = rule.get("clauses", [])
            logger.debug(f"Flag {flag.get('key', 'unknown')} rule {rule_idx}: checking {len(clauses)} clauses")

            for clause_idx, clause in enumerate(clauses):
                # Check if clause has supported attributes and operators
                is_supported = self._is_clause_supported(clause)
                logger.debug(
                    f"Flag {flag.get('key', 'unknown')} rule {rule_idx} clause {clause_idx}: {clause.get('attribute')} {clause.get('op')} -> supported: {is_supported}"
                )
                if not is_supported:
                    return False

        # Check for multiple percentage rollout rules - not supported
        percentage_rollout_count = 0
        fallthrough = env_data.get("fallthrough", {})

        # Count rules with percentage rollouts
        for rule in rules:
            if rule.get("rollout") and rule["rollout"].get("variations"):
                percentage_rollout_count += 1

        # Count fallthrough if it has percentage rollout
        if fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
            percentage_rollout_count += 1

        # Block if multiple percentage rollout rules found
        if percentage_rollout_count > 1:
            logger.debug(
                f"Flag {flag.get('key', 'unknown')} env {environment} rejected: multiple percentage rollout rules ({percentage_rollout_count}) not supported"
            )
            return False

        # Direct user targeting not supported yet (but only if non-empty)
        targets = env_data.get("targets", [])
        context_targets = env_data.get("contextTargets", [])
        if targets or context_targets:
            logger.debug(
                f"Flag {flag.get('key', 'unknown')} env {environment} rejected: has targets ({len(targets)}) or contextTargets ({len(context_targets)})"
            )
            return False

        # Must have a fallthrough rule
        fallthrough = env_data.get("fallthrough", {})
        if not fallthrough:
            logger.debug(f"Flag {flag.get('key', 'unknown')} env {environment} rejected: no fallthrough")
            return False

        # Check variant key validity
        variations = flag.get("variations", [])
        for variation in variations:
            if "value" in variation and variation["value"] not in [True, False]:
                # Check if the variation name (which becomes variant key) is valid
                variant_key = variation.get("name", "")
                if not self._is_valid_variant_key(variant_key):
                    logger.debug(
                        f"Flag {flag.get('key', 'unknown')} env {environment} rejected: invalid variant key '{variant_key}'"
                    )
                    return False

        logger.debug(f"Flag {flag.get('key', 'unknown')} accepted as importable for environment {environment}")
        return True

    def _has_progressive_rollout(self, flag, environment="production"):
        """Check if a flag uses progressive rollout patterns"""
        if not isinstance(flag, dict):
            return False

        flag_key = flag.get("key", "unknown")
        environments = flag.get("environments", {})
        env_data = environments.get(environment, {})

        if not env_data:
            return False

        # Primary Pattern: Check for experimentAllocation.type = "progressiveRollout"
        fallthrough = env_data.get("fallthrough", {})
        if fallthrough.get("rollout"):
            rollout = fallthrough["rollout"]
            experiment_allocation = rollout.get("experimentAllocation", {})

            if experiment_allocation.get("type") == "progressiveRollout":
                logger.debug(f"Flag {flag_key}: Detected progressive rollout via experimentAllocation.type")
                return True

        # Pattern 1: Check for progressive rollout in rules (only if experimentAllocation indicates it)
        rules = env_data.get("rules", [])
        for rule in rules:
            if rule.get("rollout") and rule["rollout"].get("variations"):
                rule_experiment_allocation = rule["rollout"].get("experimentAllocation", {})
                if rule_experiment_allocation.get("type") == "progressiveRollout":
                    logger.debug(f"Flag {flag_key}: Found progressive rollout in rule")
                    return True

        # Pattern 2: Check if flag name suggests progressive rollout
        flag_name = flag.get("name", "").lower()
        flag_key_lower = flag_key.lower()
        progressive_keywords = ["progressive", "rollout", "gradual", "staged", "canary", "phased"]

        if any(keyword in flag_name or keyword in flag_key_lower for keyword in progressive_keywords):
            logger.debug(f"Flag {flag_key}: Name suggests progressive rollout")
            return True

        return False

    def _is_migration_flag(self, flag):
        """Check if a flag is a migration flag (used for infrastructure/system migrations)"""
        if not isinstance(flag, dict):
            return False

        flag_key = flag.get("key", "").lower()
        flag_name = flag.get("name", "").lower()
        description = flag.get("description", "").lower()

        # Check explicit purpose field
        purpose = flag.get("_purpose")
        if purpose == "migration":
            return True

        # Check for migration keywords in flag key, name, or description
        migration_keywords = [
            "migration",
            "migrate",
            "dualwrite",
            "shadow",
            "rampdown",
            "fallback",
            "rollback",
            "cutover",
            "switch-over",
            "infrastructure",
        ]

        for keyword in migration_keywords:
            if keyword in flag_key or keyword in flag_name or keyword in description:
                return True

        # Check for classic migration stage patterns in variants
        variations = flag.get("variations", [])
        if len(variations) >= 4:  # Migration flags typically have multiple stages
            variant_values = [str(v.get("value", "")).lower() for v in variations]
            variant_names = [str(v.get("name", "")).lower() for v in variations]

            # Look for classic migration stages
            migration_stages = ["off", "dualwrite", "shadow", "live", "rampdown", "complete"]

            # Check if majority of variants match migration stages
            matching_stages = 0
            for stage in migration_stages:
                if any(stage in value or stage in name for value, name in zip(variant_values, variant_names)):
                    matching_stages += 1

            # If 4+ migration stages are present, likely a migration flag
            if matching_stages >= 4:
                return True

        # Check for temporary flag status (migration flags are often temporary)
        if flag.get("temporary", False):
            # Additional checks for temporary flags to ensure we don't exclude all temp flags
            if any(keyword in flag_key or keyword in flag_name for keyword in ["migration", "migrate", "cutover"]):
                return True

        return False

    def _is_clause_supported(self, clause):
        """Check if a LaunchDarkly clause can be converted to PostHog"""
        if not isinstance(clause, dict):
            return False

        attribute = clause.get("attribute", "")
        operator = clause.get("op", "")

        # Supported attributes (map to PostHog properties)
        supported_attributes = {
            "key",  # User ID/distinct_id
            "email",  # Email
            "name",  # Name
            "country",  # Country
            "anonymous",  # Anonymous flag
            "ip",  # IP address
            "userAgent",  # User agent
            "custom",  # Custom attributes (will need specific handling)
        }

        # Allow any custom attribute that starts with known patterns or is explicitly supported
        # This handles LaunchDarkly's flexible attribute system
        if attribute not in supported_attributes:
            # Allow any attribute - LaunchDarkly supports arbitrary custom attributes
            # We'll map them to PostHog person properties during transformation
            logger.debug(f"Allowing custom attribute: {attribute}")
            # Don't reject - allow custom attributes

        # Supported operators
        supported_operators = {
            "in",  # exact match
            "matches",  # regex
            "startsWith",  # starts with
            "endsWith",  # ends with
            "contains",  # contains
            "lessThan",  # less than
            "lessThanOrEqual",  # less than or equal
            "greaterThan",  # greater than
            "greaterThanOrEqual",  # greater than or equal
            "segmentMatch",  # segment/cohort matching
        }

        # Check if operator is supported and has values
        attribute_supported = attribute in supported_attributes or bool(attribute)  # Allow any non-empty attribute
        operator_supported = operator in supported_operators
        has_values = clause.get("values") is not None

        logger.debug(
            f"Clause validation: attribute='{attribute}' ({attribute_supported}), operator='{operator}' ({operator_supported}), has_values={has_values}"
        )

        return attribute_supported and operator_supported and has_values

    def _transform_launchdarkly_conditions(
        self, flag, environment="production", api_key=None, project_key=None, team=None
    ):
        """Transform LaunchDarkly targeting rules to PostHog condition format"""
        conditions = []

        if not isinstance(flag, dict):
            return [{"properties": [], "rollout_percentage": 0}]

        # Get specified environment from raw_environments (preferred) or transformed environments
        raw_environments = flag.get("metadata", {}).get("raw_environments", {})
        target_env = raw_environments.get(environment)

        if not target_env:
            # Fallback to transformed environments
            environments = flag.get("environments", {})
            if environment in environments:
                target_env = environments[environment]
            else:
                # Fallback to first enabled environment
                for env_data in environments.values():
                    if env_data.get("on", False):
                        target_env = env_data
                        break

        if not target_env or not target_env.get("on", False):
            return [{"properties": [], "rollout_percentage": 0}]

        # Extract targeting from specified environment
        targeting = target_env

        # Process individual target users first (if any)
        if targeting.get("targets"):
            for target in targeting["targets"]:
                if target.get("values"):  # Has specific users
                    condition = {
                        "properties": [
                            {"key": "distinct_id", "operator": "exact", "value": target["values"], "type": "person"}
                        ],
                        "rollout_percentage": 100,
                        "variant": self._get_variation_key(flag, target.get("variation")),
                    }
                    conditions.append(condition)

        # Process context targets (user segments)
        if targeting.get("contextTargets"):
            for context_target in targeting["contextTargets"]:
                if context_target.get("values"):
                    condition = {
                        "properties": [
                            {
                                "key": context_target.get("contextKind", "user"),
                                "operator": "exact",
                                "value": context_target["values"],
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": self._get_variation_key(flag, context_target.get("variation")),
                    }
                    conditions.append(condition)

        # Process custom targeting rules (this now supports attributes mapping)
        for rule_idx, rule in enumerate(targeting.get("rules", [])):
            condition = {"properties": [], "rollout_percentage": 100, "rule_id": rule.get("_id", f"rule_{rule_idx}")}

            # Transform clauses to properties (maps LaunchDarkly attributes to PostHog)
            for clause in rule.get("clauses", []):
                prop = self._transform_launchdarkly_clause(clause, api_key, project_key, environment, team)
                if prop:
                    condition["properties"].append(prop)

            # Handle rollout/variation distribution
            if rule.get("rollout"):
                # For multivariate rules with rollout, the release condition should be 100%
                # The variant distribution is handled separately in the multivariate configuration
                condition["rollout_percentage"] = 100
            elif rule.get("variation") is not None:
                # Direct variation assignment - rule serves a specific variant to 100% of matching users
                condition["rollout_percentage"] = 100
                condition["variant"] = self._get_variation_key(flag, rule.get("variation"))

            # Only add conditions that have properties (custom targeting) or specific variants
            # Also filter out conditions with 0% rollout as they serve no purpose
            if (condition["properties"] or condition.get("variant")) and condition.get("rollout_percentage", 0) > 0:
                conditions.append(condition)

        # Always add fallthrough rule if it exists - it handles users who don't match custom rules
        if targeting.get("fallthrough"):
            fallthrough = targeting["fallthrough"]

            # Determine rollout percentage based on fallthrough type
            rollout_percentage = 100  # Default
            fallthrough_variant = None

            # Handle percentage rollout in fallthrough
            if fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
                rollout = fallthrough["rollout"]
                variations = rollout["variations"]
                total_weight = sum(v.get("weight", 0) for v in variations)
                off_variation = targeting.get("offVariation", 1)

                # Calculate the percentage for the "on" variation (not the off variation)
                on_rollout_percentage = 0
                for variation_config in variations:
                    variation_index = variation_config.get("variation")
                    weight = variation_config.get("weight", 0)

                    if variation_index != off_variation and total_weight > 0:
                        # This is an "on" variation, add its percentage
                        on_rollout_percentage += int((weight / total_weight) * 100)

                        # For boolean flags, set the variant if it's the primary "on" variation
                        if flag.get("kind") == "boolean" and variation_index is not None:
                            fallthrough_variant = self._get_variation_key(flag, variation_index)
                    elif variation_index == off_variation and total_weight > 0:
                        # For multivariate flags, we might still want to track the off variation
                        if flag.get("kind") != "boolean" and variation_index is not None:
                            fallthrough_variant = self._get_variation_key(flag, variation_index)

                rollout_percentage = on_rollout_percentage

                logger.debug(
                    f"Flag {flag.get('key', 'unknown')}: Fallthrough percentage rollout calculated as {rollout_percentage}% (total weight: {total_weight})"
                )

            elif fallthrough.get("variation") is not None:
                # Handle direct variation assignment
                variation_index = fallthrough.get("variation")
                off_variation = targeting.get("offVariation", 1)

                if variation_index == off_variation:
                    rollout_percentage = 0  # Flag is off for fallthrough users
                    logger.debug(
                        f"Flag {flag.get('key', 'unknown')}: Fallthrough points to off variation ({variation_index}), setting rollout to 0%"
                    )
                else:
                    rollout_percentage = 100  # Flag is on for fallthrough users
                    logger.debug(
                        f"Flag {flag.get('key', 'unknown')}: Fallthrough points to on variation ({variation_index}), setting rollout to 100%"
                    )

                fallthrough_variant = self._get_variation_key(flag, variation_index)

            condition = {"properties": [], "rollout_percentage": rollout_percentage, "rule_id": "fallthrough"}

            # Add variant if determined
            if fallthrough_variant:
                condition["variant"] = fallthrough_variant

            # Only add fallthrough condition if it has rollout > 0%
            if rollout_percentage > 0:
                conditions.append(condition)
            else:
                logger.debug(f"Flag {flag.get('key', 'unknown')}: Skipping fallthrough condition with 0% rollout")

        # Handle case where no conditions remain (all were 0% rollout)
        if not conditions:
            logger.debug(
                f"Flag {flag.get('key', 'unknown')}: No conditions with rollout > 0%, flag effectively disabled"
            )
            # When all conditions are filtered out due to 0% rollout,
            # the flag is effectively disabled for all users
            # Return empty conditions list to represent this state
            final_conditions = []
        else:
            final_conditions = conditions

        return final_conditions

    def _transform_launchdarkly_clause(
        self, clause, api_key=None, project_key=None, environment="production", team=None
    ):
        """Transform a LaunchDarkly clause to a PostHog property"""
        if not isinstance(clause, dict):
            return None

        attribute = clause.get("attribute", "")
        operator = clause.get("op", "in")
        values = clause.get("values", [])

        # Handle segmentMatch clauses specially - create cohorts
        if attribute == "segmentMatch":
            logger.info(
                f"Processing segmentMatch clause with values: {values}, has_api_key: {bool(api_key)}, has_project_key: {bool(project_key)}, has_team: {bool(team)}"
            )

            # We can only create cohorts if we have the necessary context
            if api_key and project_key and team:
                cohort_ids = []
                for segment_key in values:
                    try:
                        # Fetch segment data
                        segment_data = self._fetch_launchdarkly_segment(api_key, project_key, segment_key, environment)
                        logger.info(f"Fetched segment {segment_key}: {segment_data}")
                        if segment_data and self._is_segment_rule_based(segment_data):
                            # Create or find cohort for this segment
                            cohort = self._find_or_create_cohort_for_segment(segment_key, segment_data, team)
                            if cohort and cohort.id:
                                # Ensure we have a valid integer ID
                                if isinstance(cohort.id, int):
                                    cohort_ids.append(cohort.id)
                                    logger.info(f"Created/found cohort {cohort.id} for segment {segment_key}")
                                else:
                                    logger.error(
                                        f"Cohort {cohort} has non-integer ID: {cohort.id} (type: {type(cohort.id)})"
                                    )
                            else:
                                logger.warning(f"Failed to create cohort for segment {segment_key}")
                        else:
                            logger.warning(f"Segment {segment_key} is list-based or invalid, skipping cohort creation")
                    except Exception as e:
                        logger.exception(f"Failed to create cohort for segment {segment_key}: {str(e)}")
                        continue

                if cohort_ids:
                    # Final safety check: ensure all IDs are integers
                    valid_cohort_ids = [cid for cid in cohort_ids if isinstance(cid, int)]
                    if not valid_cohort_ids:
                        logger.error(f"No valid integer cohort IDs found from segment keys: {values}")
                        return None

                    # Return cohort property with the created cohort IDs
                    cohort_value = valid_cohort_ids if len(valid_cohort_ids) > 1 else valid_cohort_ids[0]
                    logger.info(f"Returning cohort property with value: {cohort_value} (type: {type(cohort_value)})")

                    # Get the cohort name for display purposes
                    cohort_name = None
                    if isinstance(cohort_value, int):
                        # Try to get the cohort name from the created cohort
                        try:
                            from posthog.models import Cohort

                            cohort = Cohort.objects.get(id=cohort_value, team=team)
                            cohort_name = cohort.name
                        except Exception as e:
                            logger.warning(f"Could not fetch cohort name for ID {cohort_value}: {str(e)}")

                    cohort_property = {"key": "id", "operator": "in_cohort", "value": cohort_value, "type": "cohort"}

                    if cohort_name:
                        cohort_property["cohort_name"] = cohort_name

                    return cohort_property
                else:
                    # No valid cohorts created, return None to skip this clause
                    return None
            else:
                # Without API credentials and team context, we cannot create cohorts
                # IMPORTANT: Return None to completely skip this clause, don't fall through to regular transformation
                # This prevents segment keys (strings) from being treated as cohort IDs (integers)
                logger.warning(
                    f"Cannot transform segmentMatch clause without API credentials and team context. Segment keys: {values}"
                )
                return None

        # Map LaunchDarkly attributes to PostHog properties
        property_key = self._map_launchdarkly_attribute(attribute)

        # Handle different value types
        if not values:
            value = ""
        elif len(values) == 1:
            value = values[0]
        else:
            value = values  # Multiple values

        # Transform value for startsWith/endsWith operators
        if operator == "startsWith" and isinstance(value, str):
            # Escape special regex characters and add ^ anchor for startsWith
            import re

            escaped_value = re.escape(value)
            value = f"^{escaped_value}"
        elif operator == "endsWith" and isinstance(value, str):
            # Escape special regex characters and add $ anchor for endsWith
            import re

            escaped_value = re.escape(value)
            value = f"{escaped_value}$"

        # Map operators
        mapped_operator = self._map_launchdarkly_operator(operator)

        return {
            "key": property_key,
            "operator": mapped_operator,
            "value": value,
            "type": self._infer_launchdarkly_property_type(attribute, value),
        }

    def _map_launchdarkly_attribute(self, attribute):
        """Map LaunchDarkly attributes to PostHog property keys"""
        attribute_map = {
            "key": "distinct_id",
            "email": "email",
            "name": "name",
            "firstName": "name",
            "lastName": "name",
            "segmentMatch": "id",  # segmentMatch maps to cohort ID in PostHog
        }
        return attribute_map.get(attribute, attribute)

    def _infer_launchdarkly_property_type(self, attribute, value):
        """Infer the property type based on LaunchDarkly attribute and value"""
        # Built-in LaunchDarkly attributes
        if attribute in ["key", "email", "name", "firstName", "lastName"]:
            return "person"
        elif attribute == "segmentMatch":
            return "cohort"

        # Infer from value type
        if isinstance(value, bool):
            return "person"  # Boolean person property
        elif isinstance(value, int | float):
            return "person"  # Numeric person property
        else:
            return "person"  # Default to person property

    def _get_variation_key(self, flag, variation_index):
        """Get the variation key from the flag's variations list"""
        if variation_index is None:
            return None

        variations = flag.get("variations", [])
        if isinstance(variation_index, int) and 0 <= variation_index < len(variations):
            variation = variations[variation_index]
            return variation.get("value", str(variation_index))

        return str(variation_index)

    def _transform_launchdarkly_variants(self, flag):
        """Transform LaunchDarkly variations to PostHog variants format"""
        variations = flag.get("variations", [])
        if not variations:
            return []

        variants = []
        for idx, variation in enumerate(variations):
            # Use variation value as the key (for boolean flags, skip non-boolean variants)
            variation_value = variation.get("value")
            if variation_value in [True, False]:
                # Skip boolean variants as they don't need to be in multivariate
                continue

            # Use variation name as the key (LaunchDarkly variant key)
            variation_name = variation.get("name", f"variant_{idx}")
            variant = {
                "key": variation_name,
                "name": variation_name,
                "rollout_percentage": 0,  # Will be calculated based on targeting rules
                "value": variation_value,
                "description": variation.get("description", ""),
                "is_default": idx == 0,  # First variation is usually the "off" state
            }
            variants.append(variant)

        return variants

    def _map_launchdarkly_operator(self, ld_op):
        """Map LaunchDarkly operators to PostHog operators"""
        operator_map = {
            "in": "exact",
            "endsWith": "regex",
            "startsWith": "regex",
            "matches": "regex",
            "contains": "icontains",
            "lessThan": "lt",
            "lessThanOrEqual": "lte",
            "greaterThan": "gt",
            "greaterThanOrEqual": "gte",
            "before": "is_date_before",
            "after": "is_date_after",
            "semVerEqual": "exact",
            "semVerLessThan": "lt",
            "semVerGreaterThan": "gt",
            "segmentMatch": "in_cohort",
        }
        return operator_map.get(ld_op, "exact")

    def _fetch_launchdarkly_segment(
        self, api_key: str, project_key: str, segment_key: str, environment: str = "production"
    ):
        """Fetch segment details from LaunchDarkly API with rate limiting"""
        url = f"https://app.launchdarkly.com/api/v2/segments/{project_key}/{environment}/{segment_key}"
        headers = {"Authorization": api_key, "Content-Type": "application/json"}

        try:
            response, success = self.rate_limiter.make_request_with_rate_limiting(url, headers, max_retries=3)

            if success and response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                logger.warning(f"Segment {segment_key} fetch still rate limited after retries")
                return None
            elif response.status_code == 404:
                logger.warning(f"Segment {segment_key} not found")
                return None
            else:
                logger.warning(f"Failed to fetch segment {segment_key}: {response.status_code}")
                return None
        except Exception as e:
            logger.exception(f"Error fetching segment {segment_key}: {str(e)}")
            return None

    def _is_segment_rule_based(self, segment_data):
        """Check if a LaunchDarkly segment has rules that can be converted to PostHog cohort filters"""
        if not segment_data:
            return False

        # Check if segment has any rules that can be converted
        rules = segment_data.get("rules", [])
        has_convertible_rules = bool(rules)

        has_included = bool(segment_data.get("included", []))
        has_excluded = bool(segment_data.get("excluded", []))

        segment_key = segment_data.get("key", "unknown")

        logger.debug(
            f"Segment {segment_key}: rules={len(rules)}, included={len(segment_data.get('included', []))}, excluded={len(segment_data.get('excluded', []))}"
        )

        # We can support segments that have rules, even if they also have user lists
        # The rules will be converted to cohort filters, user lists will be ignored
        if has_convertible_rules:
            if has_included or has_excluded:
                logger.info(f"Segment {segment_key}: Has both rules and user lists - will convert rules only")
            return True
        else:
            # For testing/demo purposes, allow empty segments to create minimal cohorts
            if not has_included and not has_excluded:
                logger.info(f"Segment {segment_key}: Empty segment - will create minimal cohort for testing")
                return True
            else:
                logger.debug(f"Segment {segment_key}: No rules found - purely list-based segment")
                return False

    def _check_for_list_based_segments(self, raw_flag, environment, api_key, project_key):
        """Check if flag uses any list-based segments and return their keys"""
        list_based_segments = []

        environments = raw_flag.get("environments", {})
        env_data = environments.get(environment, {})
        rules = env_data.get("rules", [])

        # Check all segmentMatch clauses in rules
        for rule in rules:
            clauses = rule.get("clauses", [])
            for clause in clauses:
                if clause.get("op") == "segmentMatch":
                    segment_keys = clause.get("values", [])
                    for segment_key in segment_keys:
                        # Fetch segment details to check if it's list-based
                        segment_data = self._fetch_launchdarkly_segment(api_key, project_key, segment_key, environment)
                        if segment_data and not self._is_segment_rule_based(segment_data):
                            list_based_segments.append(segment_key)

        return list_based_segments

    def _convert_segment_to_cohort_filters(self, segment_data):
        """Convert LaunchDarkly segment rules to PostHog cohort filters"""
        if not segment_data:
            return []

        rules = segment_data.get("rules", [])
        segment_key = segment_data.get("key", "unknown")

        # Handle empty segments - create a filter that matches no users (more accurate)
        if not rules:
            logger.info(f"Creating empty cohort filter for segment {segment_key} with no rules")
            # Empty segments in LaunchDarkly typically match no users
            # Create a filter that will never match (distinct_id equals a non-existent value)
            return [{"key": "distinct_id", "value": "NEVER_MATCH_EMPTY_SEGMENT", "operator": "exact", "type": "person"}]

        cohort_filters = []

        logger.info(f"Converting {len(rules)} rules for segment {segment_key}")

        for rule_idx, rule in enumerate(rules):
            logger.info(f"Processing rule {rule_idx + 1} for segment {segment_key}: {rule}")
            clauses = rule.get("clauses", [])

            # Convert each clause to PostHog filter format
            for clause_idx, clause in enumerate(clauses):
                try:
                    logger.info(f"Converting clause {clause_idx + 1} of rule {rule_idx + 1}: {clause}")
                    posthog_filter = self._convert_launchdarkly_clause_to_filter(clause)
                    if posthog_filter:
                        cohort_filters.append(posthog_filter)
                        logger.info(f"Successfully converted to PostHog filter: {posthog_filter}")
                    else:
                        logger.warning(f"Clause conversion returned None: {clause}")
                except Exception as e:
                    logger.exception(f"Failed to convert clause to filter: {clause}, error: {str(e)}")
                    continue

        logger.info(f"Final cohort filters for segment {segment_key}: {cohort_filters}")
        return cohort_filters

    def _convert_launchdarkly_clause_to_filter(self, clause):
        """Transform a LaunchDarkly clause to a PostHog cohort filter"""
        if not isinstance(clause, dict):
            return None

        attribute = clause.get("attribute", "")
        operator = clause.get("op", "in")
        values = clause.get("values", [])

        # Map LaunchDarkly attributes to PostHog properties
        property_key = self._map_launchdarkly_attribute(attribute)

        # Handle different value types
        if not values:
            value = ""
        elif len(values) == 1:
            value = values[0]
        else:
            value = values  # Multiple values

        # Transform value for startsWith/endsWith operators
        if operator == "startsWith" and isinstance(value, str):
            # Escape special regex characters and add ^ anchor for startsWith
            import re

            escaped_value = re.escape(value)
            value = f"^{escaped_value}"
        elif operator == "endsWith" and isinstance(value, str):
            # Escape special regex characters and add $ anchor for endsWith
            import re

            escaped_value = re.escape(value)
            value = f"{escaped_value}$"

        # Map operators
        mapped_operator = self._map_launchdarkly_operator(operator)

        # Handle negation
        negate = clause.get("negate", False)
        if negate:
            # For negated clauses, we need to invert the operator logic
            # This is complex in PostHog, so for now we'll add a note
            logger.warning(f"Negated clause not fully supported: {clause}")
            # Could map "exact" -> "not_exact", "regex" -> "not_regex", etc.

        # Return PostHog cohort filter format
        cohort_filter = {
            "key": property_key,
            "value": value,
            "operator": mapped_operator,
            "type": self._infer_launchdarkly_property_type(attribute, value),
        }

        logger.debug(f"Converted LaunchDarkly clause to cohort filter: {clause} -> {cohort_filter}")
        return cohort_filter

    def _find_or_create_cohort_for_segment(self, segment_key, segment_data, team):
        """Find existing cohort or create new one based on segment rules"""
        from posthog.models import Cohort

        # Convert segment rules to cohort filters
        cohort_filters = self._convert_segment_to_cohort_filters(segment_data)

        if not cohort_filters:
            logger.warning(f"No valid filters found for segment {segment_key}")
            return None

        # Generate cohort name
        cohort_name = f"LaunchDarkly Segment: {segment_data.get('name', segment_key)}"

        # Check if a cohort with the same name and filters already exists
        existing_cohorts = Cohort.objects.filter(team=team, name=cohort_name, deleted=False)

        for cohort in existing_cohorts:
            # Compare filters to see if they match
            if self._cohort_filters_match(cohort.filters, cohort_filters):
                logger.info(f"Found existing cohort {cohort.id} for segment {segment_key}")
                return cohort

        # Create new cohort
        try:
            new_cohort = Cohort.objects.create(
                team=team,
                name=cohort_name,
                description=f"Auto-created from LaunchDarkly segment '{segment_key}': {segment_data.get('description', '')}",
                filters={"properties": {"type": "AND", "values": [{"type": "OR", "values": cohort_filters}]}},
                is_calculating=True,  # Enable calculation
            )

            # Trigger cohort calculation
            new_cohort.calculate_people_ch(pending_version=0)

            logger.info(f"Created new cohort {new_cohort.id} for segment {segment_key} and triggered calculation")
            return new_cohort

        except Exception as e:
            logger.exception(f"Failed to create cohort for segment {segment_key}: {str(e)}")
            return None

    def _cohort_filters_match(self, existing_filters, new_filters):
        """Check if cohort filters are equivalent"""
        # Simple comparison - can be made more sophisticated
        try:
            existing_values = existing_filters.get("properties", {}).get("values", [{}])
            if existing_values and existing_values[0].get("values"):
                existing_filter_list = existing_values[0]["values"]
                return len(existing_filter_list) == len(new_filters) and all(
                    f in existing_filter_list for f in new_filters
                )
        except (KeyError, IndexError, TypeError):
            pass
        return False

    def _fetch_launchdarkly_flags(self, api_key: str, project_key: str):
        """Fetch flags from LaunchDarkly API"""

        headers = {"Authorization": api_key, "LD-API-Version": "20240415", "Content-Type": "application/json"}

        # Step 1: Get all feature flags for the project
        list_endpoint = f"https://app.launchdarkly.com/api/v2/flags/{project_key}"
        response, success = self.rate_limiter.make_request_with_rate_limiting(list_endpoint, headers)

        if not success:
            if response.status_code == 429:
                return Response({"error": "LaunchDarkly API rate limit exceeded. Please try again later."}, status=429)
            else:
                return Response(
                    {"error": f"Failed to fetch flags list: {response.status_code} {response.reason}"}, status=400
                )

        if response.status_code == 401:
            return Response({"error": "Invalid API key. Please check your LaunchDarkly API key."}, status=401)
        elif response.status_code == 403:
            return Response(
                {"error": "Access denied. Please ensure your API key has the required permissions."}, status=403
            )
        elif response.status_code == 404:
            return Response({"error": f"Project '{project_key}' not found. Please check your project key."}, status=404)
        elif response.status_code != 200:
            return Response(
                {"error": f"Failed to fetch flags list: {response.status_code} {response.reason}"}, status=400
            )

        launchdarkly_response = response.json()
        logger.info(f"LaunchDarkly: Raw response type: {type(launchdarkly_response)}")

        # LaunchDarkly returns flags in an object with 'items' key
        if isinstance(launchdarkly_response, dict):
            flags_list = launchdarkly_response.get("items", [])
            logger.info(f"LaunchDarkly: Extracted {len(flags_list)} flags from 'items' key")
            if flags_list:
                flag_keys = [f.get("key", "no-key") for f in flags_list]
                logger.info(f"LaunchDarkly: Flag keys from list endpoint: {flag_keys}")
        else:
            # Fallback if the response is directly a list
            flags_list = launchdarkly_response if isinstance(launchdarkly_response, list) else []
            logger.info(f"LaunchDarkly: Using direct list with {len(flags_list)} flags")

        # Step 2: Get detailed information for each flag
        external_flags = []
        logger.info(f"LaunchDarkly: Processing {len(flags_list)} flags from list endpoint")
        for idx, flag_summary in enumerate(flags_list):
            try:
                flag_key = flag_summary.get("key")
                logger.info(f"LaunchDarkly: Processing flag {idx + 1}/{len(flags_list)}: {flag_key}")
                if not flag_key:
                    logger.warning(f"LaunchDarkly: Flag {idx + 1} has no key, skipping")
                    continue

                # Fetch detailed flag information including targeting rules with rate limiting
                detail_endpoint = f"https://app.launchdarkly.com/api/v2/flags/{project_key}/{flag_key}"

                # Use rate limiter for detail fetching
                logger.info(f"LaunchDarkly: Fetching details for {flag_key} from {detail_endpoint}")
                detail_response, detail_success = self.rate_limiter.make_request_with_rate_limiting(
                    detail_endpoint, headers, max_retries=3
                )

                logger.info(
                    f"LaunchDarkly: Detail fetch for {flag_key} - success: {detail_success}, status: {detail_response.status_code}"
                )

                if detail_success:
                    if detail_response.status_code == 200:
                        # Success - use detailed flag data
                        flag_detail = detail_response.json()
                        external_flags.append(flag_detail)
                        logger.info(f"LaunchDarkly: Added detailed data for {flag_key} (total: {len(external_flags)})")
                    elif detail_response.status_code == 429:
                        # Still rate limited after retries - create a special flag object indicating this
                        rate_limited_flag = dict(flag_summary)
                        rate_limited_flag["_rate_limited"] = True
                        rate_limited_flag["_rate_limit_reason"] = "Max retries exceeded due to rate limiting"
                        external_flags.append(rate_limited_flag)
                        logger.warning(
                            f"LaunchDarkly: Flag {flag_key} still rate limited after retries, using summary data (total: {len(external_flags)})"
                        )
                    else:
                        # Other expected error (401, 403, 404) - use summary data
                        logger.warning(
                            f"LaunchDarkly: Failed to fetch details for flag {flag_key}: {detail_response.status_code}, using summary data"
                        )
                        external_flags.append(flag_summary)
                        logger.info(f"LaunchDarkly: Added summary data for {flag_key} (total: {len(external_flags)})")
                else:
                    # Request completely failed (network error, unexpected status) - use summary data
                    logger.warning(f"LaunchDarkly: Request failed for flag {flag_key}, using summary data")
                    external_flags.append(flag_summary)
                    logger.info(
                        f"LaunchDarkly: Added summary data after failure for {flag_key} (total: {len(external_flags)})"
                    )
            except Exception as e:
                # Skip flags that can't be transformed
                logger.exception(
                    f"LaunchDarkly: Exception processing flag {flag_key if 'flag_key' in locals() else 'unknown'}: {str(e)}"
                )
                logger.exception(f"LaunchDarkly: Flag data: {flag_summary}")
                continue

        logger.info(f"LaunchDarkly: Returning {len(external_flags)} flags after processing")
        return external_flags

    def _fetch_amplitude_flags(self, api_key: str):
        """Fetch flags from Amplitude API"""
        import requests

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        list_endpoint = "https://experiment.amplitude.com/api/738782/flags"
        response = requests.get(list_endpoint, headers=headers, timeout=30)

        if response.status_code == 401:
            return Response({"error": "Invalid API key. Please check your Amplitude API key."}, status=401)
        elif response.status_code == 403:
            return Response(
                {"error": "Access denied. Please ensure your API key has the required permissions."}, status=403
            )
        elif response.status_code != 200:
            return Response(
                {"error": f"Failed to fetch flags list: {response.status_code} {response.reason}"}, status=400
            )

        flags_list = response.json()

        # Step 2: Fetch detailed information for each flag
        external_flags = []
        for flag_summary in flags_list:
            flag_id = flag_summary.get("id")
            if not flag_id:
                continue

            detail_endpoint = f"https://experiment.amplitude.com/api/1/flags/{flag_id}"
            detail_response = requests.get(detail_endpoint, headers=headers, timeout=30)

            if detail_response.status_code == 200:
                flag_detail = detail_response.json()
                external_flags.append(flag_detail)
            else:
                # If we can't get details for a flag, use the summary info
                external_flags.append(flag_summary)

        return external_flags

    def _transform_launchdarkly_flag_for_response(
        self, raw_flag, environment="production", api_key=None, project_key=None
    ):
        """Transform LaunchDarkly flag to PostHog response format"""
        flag_key = raw_flag.get("key", "unknown")

        # Add extensive debugging for the problematic flag
        if flag_key == "flag-with-cohort":
            logger.error(f"DEBUG FLAG {flag_key}: Full flag data keys: {list(raw_flag.keys())}")
            logger.error(f"DEBUG FLAG {flag_key}: Has environments: {'environments' in raw_flag}")
            if "environments" in raw_flag:
                envs = raw_flag.get("environments", {})
                logger.error(f"DEBUG FLAG {flag_key}: Environments type: {type(envs)}")
                logger.error(f"DEBUG FLAG {flag_key}: Environments keys: {list(envs.keys()) if envs else 'EMPTY'}")
                logger.error(f"DEBUG FLAG {flag_key}: Target environment '{environment}' exists: {environment in envs}")
                if environment in envs:
                    env_data = envs[environment]
                    logger.error(
                        f"DEBUG FLAG {flag_key}: Environment '{environment}' data keys: {list(env_data.keys())}"
                    )
                    logger.error(
                        f"DEBUG FLAG {flag_key}: Environment '{environment}' enabled: {env_data.get('on', 'KEY_NOT_FOUND')}"
                    )

        # Use raw flag data from LaunchDarkly API (not the transformed version)
        is_importable = self._check_launchdarkly_flag_importable(raw_flag, environment)
        logger.debug(f"Flag {flag_key}: importable={is_importable}")
        import_issues = []

        if not is_importable:
            # Check specific reasons for non-importability
            flag_key = raw_flag.get("key", "unknown")
            logger.debug(f"Flag {flag_key} is not importable, checking reasons...")

            # Check if this is a rate-limited flag
            if raw_flag.get("_rate_limited"):
                import_issues.append("API rate limit exceeded - try again in a few minutes")
            elif raw_flag.get("prerequisites") and len(raw_flag["prerequisites"]) > 0:
                import_issues.append("Flag prerequisites not supported")
            elif self._has_progressive_rollout(raw_flag, environment):
                import_issues.append("Progressive rollout flags not supported")
            elif self._is_migration_flag(raw_flag):
                import_issues.append("Migration flags not supported (infrastructure/system migration flags)")
            else:
                # Check environment availability
                environments = raw_flag.get("environments", {})
                logger.debug(f"Flag {flag_key}: environments={bool(environments)}, target_env={environment}")
                if not environments:
                    logger.debug(f"Flag {flag_key}: No environments found in flag data")
                    import_issues.append("No environments found")
                elif environment not in environments:
                    logger.debug(
                        f"Flag {flag_key}: Environment '{environment}' not found. Available: {list(environments.keys())}"
                    )
                    import_issues.append(f"Environment '{environment}' not found")
                else:
                    env_data = environments[environment]
                    logger.debug(
                        f"Flag {flag_key}: Environment '{environment}' found, enabled={env_data.get('on', False)}"
                    )
                    if not env_data.get("on", False):
                        import_issues.append(f"Flag is disabled in '{environment}' environment")

                # Check for targets/contextTargets
                if env_data.get("targets") or env_data.get("contextTargets"):
                    import_issues.append("Individual user targeting not supported")

                # Check fallthrough
                if not env_data.get("fallthrough"):
                    import_issues.append("No fallthrough rule found")

                # Check for multiple percentage rollout rules
                percentage_rollout_count = 0
                rules = env_data.get("rules", [])
                fallthrough = env_data.get("fallthrough", {})

                # Count rules with percentage rollouts
                for rule in rules:
                    if rule.get("rollout") and rule["rollout"].get("variations"):
                        percentage_rollout_count += 1

                # Count fallthrough if it has percentage rollout
                if fallthrough.get("rollout") and fallthrough["rollout"].get("variations"):
                    percentage_rollout_count += 1

                # Add specific error message for multiple percentage rollouts
                if percentage_rollout_count > 1:
                    import_issues.append(
                        f"Multiple percentage rollout rules not supported ({percentage_rollout_count} found)"
                    )

            # Check variant key validity
            variations = raw_flag.get("variations", [])
            invalid_variants = []
            for variation in variations:
                if "value" in variation and variation["value"] not in [True, False]:
                    variant_key = variation.get("name", "")
                    if not self._is_valid_variant_key(variant_key):
                        invalid_variants.append(variant_key)

            if invalid_variants:
                import_issues.append(
                    f"Invalid variant keys (only letters, numbers, hyphens, underscores allowed): {', '.join(invalid_variants)}"
                )

            # Check for list-based segments in segmentMatch clauses
            if api_key and project_key:
                try:
                    list_based_segments = self._check_for_list_based_segments(
                        raw_flag, environment, api_key, project_key
                    )
                    if list_based_segments:
                        import_issues.append(
                            f"List-based segments not supported (rule-based segments are supported): {', '.join(list_based_segments)}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to validate segments for flag {raw_flag.get('key', 'unknown')}: {str(e)}")
                    # Don't block import if segment validation fails - just log the warning

            # Fallback message if no specific issues found
            if not import_issues:
                import_issues.append("Flag configuration not supported")

        conditions = self._transform_launchdarkly_conditions(raw_flag, environment)

        # Get the enabled status from the selected environment
        environments = raw_flag.get("environments", {})
        selected_env = environments.get(environment, {})
        environment_enabled = selected_env.get("on", False)

        return {
            "key": raw_flag.get("key", ""),
            "name": raw_flag.get("name") or raw_flag.get("key", ""),
            "description": raw_flag.get("description", ""),
            "enabled": environment_enabled,  # Use environment-specific enabled status
            "conditions": conditions,
            "variants": self._transform_launchdarkly_variants(raw_flag),
            "metadata": {
                "provider": "launchdarkly",
                "original_id": str(raw_flag.get("_id", raw_flag.get("key", ""))),
                "created_at": raw_flag.get("creationDate"),
                "updated_at": raw_flag.get("_lastModified"),
                "environments": [environment],  # Only show the selected environment
                "tags": raw_flag.get("tags", []),
                "total_rules": len(conditions),
                "has_prerequisites": bool(raw_flag.get("prerequisites")),
                "environment_configs": self._extract_environment_data(
                    raw_flag, environment
                ),  # Filter to selected environment
                "raw_environments": raw_flag.get("environments", {}),  # Include just environment data for import
                "raw_variations": raw_flag.get("variations", []),  # Include variations for variant rollout extraction
                "raw_key": raw_flag.get("key", ""),  # Include key for debugging
                "debug_raw_flag_keys": list(raw_flag.keys()),  # Debug: see what keys are available
                "api_key": api_key,  # Store API key for cohort creation during import
                "project_key": project_key,  # Store project key for cohort creation during import
            },
            "importable": is_importable and len(import_issues) == 0,
            "import_issues": import_issues,
        }

    def _extract_environment_data(self, flag, selected_environment=None):
        """Extract environment-specific targeting data from LaunchDarkly flag"""
        environments_data = {}
        environments = flag.get("environments", {})

        # If selected_environment is specified, only process that environment
        if selected_environment:
            env_items = [(selected_environment, environments.get(selected_environment, {}))]
        else:
            env_items = environments.items()

        for env_name, env_data in env_items:
            # Get basic environment info
            is_on = env_data.get("on", False)
            rules = env_data.get("rules", [])
            targets = env_data.get("targets", [])
            context_targets = env_data.get("contextTargets", [])
            fallthrough = env_data.get("fallthrough", {})

            # Count rules and targets
            rules_count = len(rules)
            has_targets = bool(targets or context_targets)

            # Process rules with detailed information
            detailed_rules = []
            for rule in rules[:3]:  # First 3 rules only for UI performance
                rule_info = {
                    "id": rule.get("_id", ""),
                    "description": rule.get("description", ""),
                    "clauses": [],
                    "rollout_info": None,
                }

                # Process clauses (conditions)
                for clause in rule.get("clauses", []):
                    clause_info = {
                        "attribute": clause.get("attribute", ""),
                        "operator": clause.get("op", ""),
                        "values": clause.get("values", []),
                        "negate": clause.get("negate", False),
                        "context_kind": clause.get("contextKind", "user"),
                    }
                    rule_info["clauses"].append(clause_info)

                # Handle rollout or direct variation
                if rule.get("rollout"):
                    rollout = rule["rollout"]
                    variations = rollout.get("variations", [])
                    total_weight = sum(v.get("weight", 0) for v in variations)

                    rollout_info = {"type": "rollout", "variations": []}

                    for variation in variations:
                        weight = variation.get("weight", 0)
                        percentage = int((weight / total_weight) * 100) if total_weight > 0 else 0
                        rollout_info["variations"].append(
                            {"variation": variation.get("variation"), "weight": weight, "percentage": percentage}
                        )

                    rule_info["rollout_info"] = rollout_info
                elif rule.get("variation") is not None:
                    rule_info["rollout_info"] = {"type": "direct", "variation": rule.get("variation")}

                detailed_rules.append(rule_info)

            # Process fallthrough
            fallthrough_info = None
            if fallthrough:
                if fallthrough.get("rollout"):
                    rollout = fallthrough["rollout"]
                    variations = rollout.get("variations", [])
                    total_weight = sum(v.get("weight", 0) for v in variations)

                    fallthrough_info = {"type": "rollout", "variations": []}

                    for variation in variations:
                        weight = variation.get("weight", 0)
                        percentage = int((weight / total_weight) * 100) if total_weight > 0 else 0
                        fallthrough_info["variations"].append(
                            {"variation": variation.get("variation"), "weight": weight, "percentage": percentage}
                        )
                elif fallthrough.get("variation") is not None:
                    fallthrough_info = {"type": "direct", "variation": fallthrough.get("variation")}

            environments_data[env_name] = {
                "enabled": is_on,
                "rules_count": rules_count,
                "has_targets": has_targets,
                "target_count": len(targets) + len(context_targets),
                "detailed_rules": detailed_rules,
                "fallthrough": fallthrough_info,
                "off_variation": env_data.get("offVariation"),
            }

        return environments_data

    def _transform_amplitude_flag_for_response(self, flag):
        """Transform Amplitude flag to PostHog response format"""
        is_importable = self._check_amplitude_flag_importable(flag)
        import_issues = []

        if not is_importable:
            if flag.get("variants") and len(flag["variants"]) > 2:
                import_issues.append("Multiple variants not supported")
            if flag.get("bucketingKey") and flag["bucketingKey"] != "amplitude_id":
                import_issues.append("Custom bucketing keys not supported")
            if flag.get("evaluationMode") == "remote":
                import_issues.append("Remote evaluation mode not supported")

        return {
            "key": flag.get("key", ""),
            "name": flag.get("name") or flag.get("key", ""),
            "description": flag.get("description", ""),
            "enabled": bool(flag.get("enabled")),
            "conditions": self._transform_amplitude_conditions(flag),
            "variants": self._transform_amplitude_variants(flag),
            "metadata": {
                "provider": "amplitude",
                "original_id": str(flag.get("id", "")),
                "created_at": flag.get("createdAt"),
                "updated_at": flag.get("updatedAt"),
            },
            "importable": is_importable,
            "import_issues": import_issues,
        }


@receiver(model_activity_signal, sender=FeatureFlag)
def handle_feature_flag_change(sender, scope, before_update, after_update, activity, was_impersonated=False, **kwargs):
    # Extract scheduled change context if present
    scheduled_change_context = getattr(after_update, "_scheduled_change_context", {})
    scheduled_change_id = scheduled_change_context.get("scheduled_change_id")
    is_scheduled_change = scheduled_change_id is not None

    # Create trigger info for scheduled changes
    trigger = None
    if is_scheduled_change:
        from posthog.models.activity_logging.activity_log import Trigger

        trigger = Trigger(
            job_type="scheduled_change",
            job_id=str(scheduled_change_id),
            payload={"scheduled_change_id": scheduled_change_id},
        )

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.last_modified_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.key,
            trigger=trigger,
        ),
    )


class LegacyFeatureFlagViewSet(FeatureFlagViewSet):
    param_derived_from_user_current_team = "project_id"
