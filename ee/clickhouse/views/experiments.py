from copy import deepcopy
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from django.db.models import Case, F, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Now

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ActionsNode, ExperimentEventExposureConfig

from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models import Survey
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.cohort import Cohort
from posthog.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
)
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagEvaluationTag
from posthog.models.filters.filter import Filter
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team.team import Team
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.utils import str_to_bool

from products.product_tours.backend.models import ProductTour

from ee.clickhouse.queries.experiments.utils import requires_flag_warning
from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutSerializer
from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer


class ExperimentSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    feature_flag_key = serializers.CharField(source="get_feature_flag_key")
    created_by = UserBasicSerializer(read_only=True)
    feature_flag = MinimalFeatureFlagSerializer(read_only=True)
    holdout = ExperimentHoldoutSerializer(read_only=True)
    holdout_id = serializers.PrimaryKeyRelatedField(
        queryset=ExperimentHoldout.objects.all(), source="holdout", required=False, allow_null=True
    )
    saved_metrics = ExperimentToSavedMetricSerializer(many=True, source="experimenttosavedmetric_set", read_only=True)
    saved_metrics_ids = serializers.ListField(child=serializers.JSONField(), required=False, allow_null=True)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Experiment
        fields = [
            "id",
            "name",
            "description",
            "start_date",
            "end_date",
            "feature_flag_key",
            "feature_flag",
            "holdout",
            "holdout_id",
            "exposure_cohort",
            "parameters",
            "secondary_metrics",
            "saved_metrics",
            "saved_metrics_ids",
            "filters",
            "archived",
            "deleted",
            "created_by",
            "created_at",
            "updated_at",
            "type",
            "exposure_criteria",
            "metrics",
            "metrics_secondary",
            "stats_config",
            "_create_in_folder",
            "conclusion",
            "conclusion_comment",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "feature_flag",
            "exposure_cohort",
            "holdout",
            "saved_metrics",
            "user_access_level",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Normalize query date ranges to the experiment's current range
        # Cribbed from ExperimentTrendsQuery
        new_date_range = {
            "date_from": data["start_date"] if data["start_date"] else "",
            "date_to": data["end_date"] if data["end_date"] else "",
            "explicitDate": True,
        }
        for metrics_list in [data.get("metrics", []), data.get("metrics_secondary", [])]:
            for metric in metrics_list:
                if metric.get("count_query", {}).get("dateRange"):
                    metric["count_query"]["dateRange"] = new_date_range
                if metric.get("funnels_query", {}).get("dateRange"):
                    metric["funnels_query"]["dateRange"] = new_date_range

        for saved_metric in data.get("saved_metrics", []):
            if saved_metric.get("query", {}).get("count_query", {}).get("dateRange"):
                saved_metric["query"]["count_query"]["dateRange"] = new_date_range
            if saved_metric.get("query", {}).get("funnels_query", {}).get("dateRange"):
                saved_metric["query"]["funnels_query"]["dateRange"] = new_date_range

            # Add fingerprint to saved metric returned from API
            # so that frontend knows what timeseries records to query
            if saved_metric.get("query"):
                saved_metric["query"]["fingerprint"] = compute_metric_fingerprint(
                    saved_metric["query"],
                    instance.start_date,
                    get_experiment_stats_method(instance),
                    instance.exposure_criteria,
                )

        return data

    def validate_saved_metrics_ids(self, value):
        if value is None:
            return value

        # check value is valid json list with id and optionally metadata param
        if not isinstance(value, list):
            raise ValidationError("Saved metrics must be a list")

        for saved_metric in value:
            if not isinstance(saved_metric, dict):
                raise ValidationError("Saved metric must be an object")
            if "id" not in saved_metric:
                raise ValidationError("Saved metric must have an id")
            if "metadata" in saved_metric and not isinstance(saved_metric["metadata"], dict):
                raise ValidationError("Metadata must be an object")

            # metadata is optional, but if it exists, should have type key
            # TODO: extend with other metadata keys when known
            if "metadata" in saved_metric and "type" not in saved_metric["metadata"]:
                raise ValidationError("Metadata must have a type key")

        # check if all saved metrics exist and belong to the same team
        saved_metrics = ExperimentSavedMetric.objects.filter(
            id__in=[saved_metric["id"] for saved_metric in value], team_id=self.context["team_id"]
        )
        if saved_metrics.count() != len(value):
            raise ValidationError("Saved metric does not exist or does not belong to this project")

        return value

    def validate(self, data):
        # Validate start/end dates
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Only validate if both dates are present
        if start_date and end_date and start_date >= end_date:
            raise ValidationError("End date must be after start date")

        return super().validate(data)

    def validate_parameters(self, value):
        if not value:
            return value

        variants = value.get("feature_flag_variants", [])

        if len(variants) >= 21:
            raise ValidationError("Feature flag variants must be less than 21")
        elif len(variants) > 0:
            if "control" not in [variant["key"] for variant in variants]:
                raise ValidationError("Feature flag variants must contain a control variant")

        return value

    def validate_existing_feature_flag_for_experiment(self, feature_flag: FeatureFlag):
        variants = feature_flag.filters.get("multivariate", {}).get("variants", [])

        if len(variants) and len(variants) > 1:
            if variants[0].get("key") != "control":
                raise ValidationError("Feature flag must have control as the first variant.")
            return True

        raise ValidationError("Feature flag is not eligible for experiments.")

    def validate_exposure_criteria(self, exposure_criteria: dict | None):
        if not exposure_criteria:
            return exposure_criteria

        if "filterTestAccounts" in exposure_criteria and not isinstance(exposure_criteria["filterTestAccounts"], bool):
            raise ValidationError("filterTestAccounts must be a boolean")

        if "exposure_config" in exposure_criteria:
            exposure_config = exposure_criteria["exposure_config"]
            try:
                if exposure_config.get("kind") == "ActionsNode":
                    ActionsNode.model_validate(exposure_config)
                else:
                    ExperimentEventExposureConfig.model_validate(exposure_config)
                return exposure_criteria
            except Exception:
                raise ValidationError("Invalid exposure criteria")

        return exposure_criteria

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        is_draft = "start_date" not in validated_data or validated_data["start_date"] is None

        # if not validated_data.get("filters") and not is_draft:
        #     raise ValidationError("Filters are required when creating a launched experiment")

        saved_metrics_data = validated_data.pop("saved_metrics_ids", [])

        variants = []
        aggregation_group_type_index = None
        if "parameters" in validated_data:
            if validated_data["parameters"] is not None:
                variants = validated_data["parameters"].get("feature_flag_variants", [])
                aggregation_group_type_index = validated_data["parameters"].get("aggregation_group_type_index")

        request = self.context["request"]
        validated_data["created_by"] = request.user

        feature_flag_key = validated_data.pop("get_feature_flag_key")

        existing_feature_flag = FeatureFlag.objects.filter(
            key=feature_flag_key, team_id=self.context["team_id"], deleted=False
        ).first()
        if existing_feature_flag:
            self.validate_existing_feature_flag_for_experiment(existing_feature_flag)
            feature_flag = existing_feature_flag
        else:
            holdout_groups = None
            if validated_data.get("holdout"):
                holdout_groups = validated_data["holdout"].filters

            default_variants = [
                {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
            ]

            feature_flag_filters = {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": variants or default_variants},
                "aggregation_group_type_index": aggregation_group_type_index,
                "holdout_groups": holdout_groups,
            }

            feature_flag_data = {
                "key": feature_flag_key,
                "name": f"Feature Flag for Experiment {validated_data['name']}",
                "filters": feature_flag_filters,
                "active": not is_draft,
                "creation_context": "experiments",
            }

            # Pass ensure_experience_continuity from experiment parameters
            parameters = validated_data.get("parameters") or {}
            if parameters.get("ensure_experience_continuity") is not None:
                feature_flag_data["ensure_experience_continuity"] = parameters["ensure_experience_continuity"]
            if validated_data.get("_create_in_folder") is not None:
                feature_flag_data["_create_in_folder"] = validated_data["_create_in_folder"]
            feature_flag_serializer = FeatureFlagSerializer(
                data=feature_flag_data,
                context=self.context,
            )

            feature_flag_serializer.is_valid(raise_exception=True)
            feature_flag = feature_flag_serializer.save()

        # Ensure stats_config has a method set, preserving any other fields passed from frontend
        stats_config = validated_data.get("stats_config", {})
        if not stats_config.get("method"):
            # Get organization's default stats method setting
            team = Team.objects.get(id=self.context["team_id"])
            default_method = team.organization.default_experiment_stats_method
            stats_config["method"] = default_method
            validated_data["stats_config"] = stats_config

        # Add fingerprints to metrics
        # UI creates experiments without metrics (adds them later in draft mode)
        # But API can create+launch experiments with metrics in one call
        for metric_field in ["metrics", "metrics_secondary"]:
            if metric_field in validated_data:
                for metric in validated_data[metric_field]:
                    stats_method = "bayesian" if stats_config is None else stats_config.get("method", "bayesian")
                    metric["fingerprint"] = compute_metric_fingerprint(
                        metric, validated_data.get("start_date"), stats_method, validated_data.get("exposure_criteria")
                    )

        # Sync ordering arrays for inline metrics (all metrics are "new" in create)
        if "metrics" in validated_data:
            primary_ordering = list(validated_data.get("primary_metrics_ordered_uuids") or [])
            for metric in validated_data["metrics"]:
                if uuid := metric.get("uuid"):
                    if uuid not in primary_ordering:
                        primary_ordering.append(uuid)
            validated_data["primary_metrics_ordered_uuids"] = primary_ordering

        if "metrics_secondary" in validated_data:
            secondary_ordering = list(validated_data.get("secondary_metrics_ordered_uuids") or [])
            for metric in validated_data["metrics_secondary"]:
                if uuid := metric.get("uuid"):
                    if uuid not in secondary_ordering:
                        secondary_ordering.append(uuid)
            validated_data["secondary_metrics_ordered_uuids"] = secondary_ordering

        experiment = Experiment.objects.create(
            team_id=self.context["team_id"], feature_flag=feature_flag, **validated_data
        )

        # if this is a web experiment, copy over the variant data to the experiment itself.
        if validated_data.get("type", "") == "web":
            web_variants = {}
            ff_variants = variants or default_variants

            for variant in ff_variants:
                web_variants[variant.get("key")] = {
                    "rollout_percentage": variant.get("rollout_percentage"),
                }

            experiment.variants = web_variants
            experiment.save()

        if saved_metrics_data:
            for saved_metric_data in saved_metrics_data:
                saved_metric_serializer = ExperimentToSavedMetricSerializer(
                    data={
                        "experiment": experiment.id,
                        "saved_metric": saved_metric_data["id"],
                        "metadata": saved_metric_data.get("metadata"),
                    },
                    context=self.context,
                )
                saved_metric_serializer.is_valid(raise_exception=True)
                saved_metric_serializer.save()

            # Sync ordering arrays for saved metrics (all are "new" in create)
            primary_ordering = list(experiment.primary_metrics_ordered_uuids or [])
            secondary_ordering = list(experiment.secondary_metrics_ordered_uuids or [])
            ordering_changed = False

            saved_metric_ids = [sm["id"] for sm in saved_metrics_data]
            saved_metrics_map = {sm.id: sm for sm in ExperimentSavedMetric.objects.filter(id__in=saved_metric_ids)}

            for sm_data in saved_metrics_data:
                saved_metric = saved_metrics_map.get(sm_data["id"])
                if saved_metric and saved_metric.query:
                    if uuid := saved_metric.query.get("uuid"):
                        metric_type = (sm_data.get("metadata") or {}).get("type", "primary")
                        if metric_type == "primary":
                            if uuid not in primary_ordering:
                                primary_ordering.append(uuid)
                                ordering_changed = True
                        else:
                            if uuid not in secondary_ordering:
                                secondary_ordering.append(uuid)
                                ordering_changed = True

            if ordering_changed:
                experiment.primary_metrics_ordered_uuids = primary_ordering
                experiment.secondary_metrics_ordered_uuids = secondary_ordering
                experiment.save(update_fields=["primary_metrics_ordered_uuids", "secondary_metrics_ordered_uuids"])

        self._validate_metric_ordering(experiment, {})

        return experiment

    def update(self, instance: Experiment, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        # if (
        #     not instance.filters.get("events")
        #     and not instance.filters.get("actions")
        #     and not instance.filters.get("data_warehouse")
        #     and validated_data.get("start_date")
        #     and not validated_data.get("filters")
        # ):
        #     raise ValidationError("Filters are required when launching an experiment")

        update_saved_metrics = "saved_metrics_ids" in validated_data
        saved_metrics_data = validated_data.pop("saved_metrics_ids", []) or []

        # Capture old saved metric UUIDs BEFORE delete for ordering sync
        old_saved_metric_uuids: dict[str, set[str]] = {"primary": set(), "secondary": set()}
        if update_saved_metrics:
            for link in instance.experimenttosavedmetric_set.select_related("saved_metric").all():
                if link.saved_metric.query:
                    uuid = link.saved_metric.query.get("uuid")
                    if uuid:
                        metric_type = (link.metadata or {}).get("type", "primary")
                        if metric_type == "primary":
                            old_saved_metric_uuids["primary"].add(uuid)
                        else:
                            old_saved_metric_uuids["secondary"].add(uuid)

        # We replace all saved metrics on update to avoid issues with partial updates
        if update_saved_metrics:
            instance.experimenttosavedmetric_set.all().delete()
            for saved_metric_data in saved_metrics_data:
                saved_metric_serializer = ExperimentToSavedMetricSerializer(
                    data={
                        "experiment": instance.id,
                        "saved_metric": saved_metric_data["id"],
                        "metadata": saved_metric_data.get("metadata"),
                    },
                    context=self.context,
                )
                saved_metric_serializer.is_valid(raise_exception=True)
                saved_metric_serializer.save()

        has_start_date = validated_data.get("start_date") is not None
        feature_flag = instance.feature_flag

        expected_keys = {
            "name",
            "description",
            "start_date",
            "end_date",
            "filters",
            "parameters",
            "archived",
            "deleted",
            "secondary_metrics",
            "holdout",
            "exposure_criteria",
            "metrics",
            "metrics_secondary",
            "stats_config",
            "conclusion",
            "conclusion_comment",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
        }
        given_keys = set(validated_data.keys())
        extra_keys = given_keys - expected_keys

        if feature_flag.key == validated_data.get("get_feature_flag_key"):
            extra_keys.remove("get_feature_flag_key")

        if extra_keys:
            raise ValidationError(f"Can't update keys: {', '.join(sorted(extra_keys))} on Experiment")

        # if an experiment has launched, we cannot edit its variants or holdout anymore.
        if not instance.is_draft:
            if "feature_flag_variants" in validated_data.get("parameters", {}):
                if len(validated_data["parameters"]["feature_flag_variants"]) != len(feature_flag.variants):
                    raise ValidationError("Can't update feature_flag_variants on Experiment")

                for variant in validated_data["parameters"]["feature_flag_variants"]:
                    if (
                        len([ff_variant for ff_variant in feature_flag.variants if ff_variant["key"] == variant["key"]])
                        != 1
                    ):
                        raise ValidationError("Can't update feature_flag_variants on Experiment")
            if "holdout" in validated_data and validated_data["holdout"] != instance.holdout:
                raise ValidationError("Can't update holdout on running Experiment")

        properties = validated_data.get("filters", {}).get("properties")
        if properties:
            raise ValidationError("Experiments do not support global filter properties")

        if instance.is_draft:
            # if feature flag variants or holdout have changed, update the feature flag.
            holdout_groups = instance.holdout.filters if instance.holdout else None
            if "holdout" in validated_data:
                holdout_groups = validated_data["holdout"].filters if validated_data["holdout"] else None

            if validated_data.get("parameters"):
                variants = validated_data["parameters"].get("feature_flag_variants", [])
                aggregation_group_type_index = validated_data["parameters"].get("aggregation_group_type_index")

                global_filters = validated_data.get("filters")
                properties = []
                if global_filters:
                    properties = global_filters.get("properties", [])
                    if properties:
                        raise ValidationError("Experiments do not support global filter properties")

                default_variants = [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                ]

                feature_flag_filters = feature_flag.filters
                feature_flag_filters["groups"] = feature_flag.filters.get("groups", [])
                feature_flag_filters["multivariate"] = {"variants": variants or default_variants}
                feature_flag_filters["aggregation_group_type_index"] = aggregation_group_type_index
                feature_flag_filters["holdout_groups"] = holdout_groups

                existing_flag_serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={"filters": feature_flag_filters},
                    partial=True,
                    context=self.context,
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                existing_flag_serializer.save()
            else:
                # no parameters provided, just update the holdout if necessary
                if "holdout" in validated_data:
                    existing_flag_serializer = FeatureFlagSerializer(
                        feature_flag,
                        data={"filters": {**feature_flag.filters, "holdout_groups": holdout_groups}},
                        partial=True,
                        context=self.context,
                    )
                    existing_flag_serializer.is_valid(raise_exception=True)
                    existing_flag_serializer.save()

        # Always recalculate fingerprints for all metrics
        # Fingerprints depend on start_date, stats_config, and exposure_criteria
        start_date = validated_data.get("start_date", instance.start_date)
        stats_config = validated_data.get("stats_config", instance.stats_config)
        exposure_criteria = validated_data.get("exposure_criteria", instance.exposure_criteria)

        for metric_field in ["metrics", "metrics_secondary"]:
            # Use metrics from validated_data if present, otherwise use existing metrics
            metrics = validated_data.get(metric_field, getattr(instance, metric_field, None))
            if metrics:
                updated_metrics = []
                for metric in metrics:
                    metric_copy = deepcopy(metric)
                    stats_method = "bayesian" if stats_config is None else stats_config.get("method", "bayesian")
                    metric_copy["fingerprint"] = compute_metric_fingerprint(
                        metric_copy,
                        start_date,
                        stats_method,
                        exposure_criteria,
                    )
                    updated_metrics.append(metric_copy)

                validated_data[metric_field] = updated_metrics

        self._sync_ordering_with_metric_changes(instance, validated_data)
        self._sync_ordering_for_saved_metrics(
            instance,
            validated_data,
            old_saved_metric_uuids,
            saved_metrics_data if update_saved_metrics else None,
        )
        self._validate_metric_ordering(instance, validated_data)

        if instance.is_draft and has_start_date:
            feature_flag.active = True
            feature_flag.save()
            return super().update(instance, validated_data)
        else:
            # Not a draft, doesn't have start date
            # Or draft without start date
            return super().update(instance, validated_data)

    def _sync_ordering_with_metric_changes(self, instance: Experiment, validated_data: dict) -> None:
        """
        Sync ordering arrays with inline metric changes in this request.

        When metrics are added/removed, their UUIDs should be added/removed from
        the ordering arrays. This handles the case where API consumers send metrics
        without also updating the ordering arrays.
        """
        if "metrics" in validated_data:
            old_uuids = {m.get("uuid") for m in instance.metrics or [] if m.get("uuid")}
            new_uuids = {m.get("uuid") for m in validated_data.get("metrics") or [] if m.get("uuid")}

            added = new_uuids - old_uuids
            removed = old_uuids - new_uuids

            if added or removed:
                # Use ordering from request if explicitly provided, otherwise use instance's ordering
                if "primary_metrics_ordered_uuids" in validated_data:
                    current_ordering = list(validated_data["primary_metrics_ordered_uuids"] or [])
                else:
                    current_ordering = list(instance.primary_metrics_ordered_uuids or [])

                current_ordering = [u for u in current_ordering if u not in removed]
                for uuid in added:
                    if uuid not in current_ordering:
                        current_ordering.append(uuid)

                validated_data["primary_metrics_ordered_uuids"] = current_ordering

        if "metrics_secondary" in validated_data:
            old_uuids = {m.get("uuid") for m in instance.metrics_secondary or [] if m.get("uuid")}
            new_uuids = {m.get("uuid") for m in validated_data.get("metrics_secondary") or [] if m.get("uuid")}

            added = new_uuids - old_uuids
            removed = old_uuids - new_uuids

            if added or removed:
                if "secondary_metrics_ordered_uuids" in validated_data:
                    current_ordering = list(validated_data["secondary_metrics_ordered_uuids"] or [])
                else:
                    current_ordering = list(instance.secondary_metrics_ordered_uuids or [])

                current_ordering = [u for u in current_ordering if u not in removed]

                for uuid in added:
                    if uuid not in current_ordering:
                        current_ordering.append(uuid)

                validated_data["secondary_metrics_ordered_uuids"] = current_ordering

    def _sync_ordering_for_saved_metrics(
        self,
        instance: Experiment,
        validated_data: dict,
        old_saved_metric_uuids: dict[str, set[str]],
        saved_metrics_data: list[dict] | None,
    ) -> None:
        """
        Sync ordering arrays with saved metric changes in this request.

        Since saved_metrics_ids is popped from validated_data early and saved metrics
        are deleted/recreated before this runs, we need the old UUIDs passed in.

        Args:
            instance: The experiment being updated
            validated_data: The validated data dict (will be modified)
            old_saved_metric_uuids: Dict with 'primary' and 'secondary' keys containing old UUIDs
            saved_metrics_data: The new saved_metrics_ids from the request, or None if not updating
        """
        if saved_metrics_data is None:
            return

        new_primary_uuids: set[str] = set()
        new_secondary_uuids: set[str] = set()

        saved_metric_ids_list = [sm["id"] for sm in saved_metrics_data]
        if saved_metric_ids_list:
            saved_metrics = {sm.id: sm for sm in ExperimentSavedMetric.objects.filter(id__in=saved_metric_ids_list)}

            for sm_data in saved_metrics_data:
                saved_metric = saved_metrics.get(sm_data["id"])
                if saved_metric and saved_metric.query:
                    uuid = saved_metric.query.get("uuid")
                    if uuid:
                        metric_type = (sm_data.get("metadata") or {}).get("type", "primary")
                        if metric_type == "primary":
                            new_primary_uuids.add(uuid)
                        else:
                            new_secondary_uuids.add(uuid)

        added_primary = new_primary_uuids - old_saved_metric_uuids["primary"]
        removed_primary = old_saved_metric_uuids["primary"] - new_primary_uuids
        added_secondary = new_secondary_uuids - old_saved_metric_uuids["secondary"]
        removed_secondary = old_saved_metric_uuids["secondary"] - new_secondary_uuids

        if added_primary or removed_primary:
            if "primary_metrics_ordered_uuids" in validated_data:
                current_ordering = list(validated_data["primary_metrics_ordered_uuids"] or [])
            else:
                current_ordering = list(instance.primary_metrics_ordered_uuids or [])

            current_ordering = [u for u in current_ordering if u not in removed_primary]
            for uuid in added_primary:
                if uuid not in current_ordering:
                    current_ordering.append(uuid)
            validated_data["primary_metrics_ordered_uuids"] = current_ordering

        if added_secondary or removed_secondary:
            if "secondary_metrics_ordered_uuids" in validated_data:
                current_ordering = list(validated_data["secondary_metrics_ordered_uuids"] or [])
            else:
                current_ordering = list(instance.secondary_metrics_ordered_uuids or [])

            current_ordering = [u for u in current_ordering if u not in removed_secondary]
            for uuid in added_secondary:
                if uuid not in current_ordering:
                    current_ordering.append(uuid)
            validated_data["secondary_metrics_ordered_uuids"] = current_ordering

    def _validate_metric_ordering(self, instance: Experiment, validated_data: dict) -> None:
        """
        Validate that ordering arrays contain all metric UUIDs.

        This catches bugs where the frontend sends metrics but fails to include
        their UUIDs in the ordering arrays
        """
        primary_ordering = validated_data.get("primary_metrics_ordered_uuids", instance.primary_metrics_ordered_uuids)
        secondary_ordering = validated_data.get(
            "secondary_metrics_ordered_uuids", instance.secondary_metrics_ordered_uuids
        )

        # Get inline metrics
        primary_metrics = validated_data.get("metrics", instance.metrics) or []
        secondary_metrics = validated_data.get("metrics_secondary", instance.metrics_secondary) or []

        # Get saved metrics from the db (they were just created/recreated in update())
        saved_metrics = list(instance.experimenttosavedmetric_set.select_related("saved_metric").all())

        expected_primary_uuids: set[str] = set()
        expected_secondary_uuids: set[str] = set()

        # Add inline metric UUIDs
        for metric in primary_metrics:
            uuid = metric.get("uuid")
            if uuid:
                expected_primary_uuids.add(uuid)

        for metric in secondary_metrics:
            uuid = metric.get("uuid")
            if uuid:
                expected_secondary_uuids.add(uuid)

        # Add saved metric UUIDs
        for link in saved_metrics:
            saved_metric = link.saved_metric
            uuid = saved_metric.query.get("uuid") if saved_metric.query else None
            if uuid:
                metric_type = link.metadata.get("type", "primary") if link.metadata else "primary"
                if metric_type == "primary":
                    expected_primary_uuids.add(uuid)
                else:
                    expected_secondary_uuids.add(uuid)

        # Validate: if there are primary metrics, ordering array must exist and contain all UUIDs
        if expected_primary_uuids:
            if primary_ordering is None:
                raise ValidationError(
                    "primary_metrics_ordered_uuids is null but primary metrics exist. "
                    "This is likely a frontend bug - please refresh and try again."
                )
            missing = expected_primary_uuids - set(primary_ordering)
            if missing:
                raise ValidationError(
                    f"primary_metrics_ordered_uuids is missing UUIDs: {sorted(missing)}. "
                    "This is likely a frontend bug - please refresh and try again."
                )

        # Validate: if there are secondary metrics, ordering array must exist and contain all UUIDs
        if expected_secondary_uuids:
            if secondary_ordering is None:
                raise ValidationError(
                    "secondary_metrics_ordered_uuids is null but secondary metrics exist. "
                    "This is likely a frontend bug - please refresh and try again."
                )
            missing = expected_secondary_uuids - set(secondary_ordering)
            if missing:
                raise ValidationError(
                    f"secondary_metrics_ordered_uuids is missing UUIDs: {sorted(missing)}. "
                    "This is likely a frontend bug - please refresh and try again."
                )


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETE = "complete"
    ALL = "all"


class EnterpriseExperimentsViewSet(
    ForbidDestroyModel, TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet
):
    scope_object: Literal["experiment"] = "experiment"
    serializer_class = ExperimentSerializer
    queryset = Experiment.objects.prefetch_related(
        "feature_flag", "created_by", "holdout", "experimenttosavedmetric_set", "saved_metrics"
    ).all()
    ordering = "-created_at"

    def safely_get_queryset(self, queryset) -> QuerySet:
        """Override to filter out deleted experiments and apply filters."""
        include_deleted = False
        if self.action in ("partial_update", "update") and hasattr(self, "request"):
            deleted_value = self.request.data.get("deleted")
            if deleted_value is not None:
                include_deleted = not str_to_bool(deleted_value)

        if not include_deleted:
            queryset = queryset.exclude(deleted=True)

        # Only apply filters for list view, not detail view
        if self.action == "list":
            # filtering by status
            status = self.request.query_params.get("status")
            if status:
                try:
                    status_enum = ExperimentStatus(status.lower())
                except ValueError:
                    status_enum = None

                if status_enum and status_enum != ExperimentStatus.ALL:
                    if status_enum == ExperimentStatus.DRAFT:
                        queryset = queryset.filter(start_date__isnull=True)
                    elif status_enum == ExperimentStatus.RUNNING:
                        queryset = queryset.filter(start_date__isnull=False, end_date__isnull=True)
                    elif status_enum == ExperimentStatus.COMPLETE:
                        queryset = queryset.filter(end_date__isnull=False)

            # filtering by creator id
            created_by_id = self.request.query_params.get("created_by_id")
            if created_by_id:
                queryset = queryset.filter(created_by_id=created_by_id)

            # archived
            archived = self.request.query_params.get("archived")
            if archived is not None:
                archived_bool = archived.lower() == "true"
                queryset = queryset.filter(archived=archived_bool)
            else:
                queryset = queryset.filter(archived=False)

        # search by name
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(Q(name__icontains=search))

        # Ordering
        order = self.request.query_params.get("order")
        if order:
            # Handle computed field sorting
            if order in ["duration", "-duration"]:
                # Duration = end_date - start_date (or now() - start_date if running)
                queryset = queryset.annotate(
                    computed_duration=Case(
                        When(start_date__isnull=True, then=Value(None)),
                        When(end_date__isnull=False, then=F("end_date") - F("start_date")),
                        default=Now() - F("start_date"),
                    )
                )
                queryset = queryset.order_by(f"{'-' if order.startswith('-') else ''}computed_duration")
            elif order in ["status", "-status"]:
                # Status ordering: Draft (no start) -> Running (no end) -> Complete (has end)
                # Annotate with numeric status values for clear ordering
                queryset = queryset.annotate(
                    computed_status=Case(
                        When(start_date__isnull=True, then=Value(0)),  # Draft
                        When(end_date__isnull=True, then=Value(1)),  # Running
                        default=Value(2),  # Complete
                    )
                )
                if order.startswith("-"):
                    # Descending: Complete -> Running -> Draft
                    queryset = queryset.order_by(F("computed_status").desc())
                else:
                    # Ascending: Draft -> Running -> Complete
                    queryset = queryset.order_by(F("computed_status").asc())
            else:
                queryset = queryset.order_by(order)

        return queryset

    # ******************************************
    # /projects/:id/experiments/requires_flag_implementation
    #
    # Returns current results of an experiment, and graphs
    # 1. Probability of success
    # 2. Funnel breakdown graph to display
    # ******************************************
    @action(methods=["GET"], detail=False, required_scopes=["experiment:read"])
    def requires_flag_implementation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filter = Filter(request=request, team=self.team).shallow_clone({"date_from": "-7d", "date_to": ""})

        warning = requires_flag_warning(filter, self.team)

        return Response({"result": warning})

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def duplicate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source_experiment: Experiment = self.get_object()

        # Allow overriding the feature flag key from the request
        feature_flag_key = request.data.get("feature_flag_key", source_experiment.feature_flag.key)

        # Check if the feature flag key refers to an existing flag with different variants
        # If so, we need to update parameters.feature_flag_variants to match the new flag
        parameters = deepcopy(source_experiment.parameters) or {}
        if feature_flag_key != source_experiment.feature_flag.key:
            existing_flag = FeatureFlag.objects.filter(
                key=feature_flag_key, team_id=self.team_id, deleted=False
            ).first()
            if existing_flag and existing_flag.filters.get("multivariate", {}).get("variants"):
                parameters["feature_flag_variants"] = existing_flag.filters["multivariate"]["variants"]

        # Generate a unique name for the duplicate
        base_name = f"{source_experiment.name} (Copy)"
        duplicate_name = base_name
        counter = 1
        while Experiment.objects.filter(team_id=self.team_id, name=duplicate_name, deleted=False).exists():
            duplicate_name = f"{base_name} {counter}"
            counter += 1

        # Prepare saved metrics data for the serializer
        saved_metrics_data = []
        for experiment_to_saved_metric in source_experiment.experimenttosavedmetric_set.all():
            saved_metrics_data.append(
                {
                    "id": experiment_to_saved_metric.saved_metric.id,
                    "metadata": experiment_to_saved_metric.metadata,
                }
            )

        # Prepare data for duplication
        duplicate_data = {
            "name": duplicate_name,
            "description": source_experiment.description,
            "type": source_experiment.type,
            "parameters": parameters,
            "filters": source_experiment.filters,
            "metrics": source_experiment.metrics,
            "metrics_secondary": source_experiment.metrics_secondary,
            "stats_config": source_experiment.stats_config,
            "exposure_criteria": source_experiment.exposure_criteria,
            "saved_metrics_ids": saved_metrics_data,
            "feature_flag_key": feature_flag_key,  # Use provided key or fall back to existing
            "primary_metrics_ordered_uuids": source_experiment.primary_metrics_ordered_uuids,
            "secondary_metrics_ordered_uuids": source_experiment.secondary_metrics_ordered_uuids,
            # Reset fields for new experiment
            "start_date": None,
            "end_date": None,
            "archived": False,
            "deleted": False,
        }

        # Create the duplicate experiment using the serializer
        duplicate_serializer = ExperimentSerializer(
            data=duplicate_data,
            context=self.get_serializer_context(),
        )
        duplicate_serializer.is_valid(raise_exception=True)
        duplicate_experiment = duplicate_serializer.save()

        return Response(
            ExperimentSerializer(duplicate_experiment, context=self.get_serializer_context()).data, status=201
        )

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def create_exposure_cohort_for_experiment(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment = self.get_object()
        flag = getattr(experiment, "feature_flag", None)
        if not flag:
            raise ValidationError("Experiment does not have a feature flag")

        if not experiment.start_date:
            raise ValidationError("Experiment does not have a start date")

        if experiment.exposure_cohort:
            raise ValidationError("Experiment already has an exposure cohort")

        exposure_filter_data = (experiment.parameters or {}).get("custom_exposure_filter")
        exposure_filter = None
        if exposure_filter_data:
            exposure_filter = Filter(data={**exposure_filter_data, "is_simplified": True}, team=experiment.team)

        target_entity: int | str = "$feature_flag_called"
        target_entity_type = "events"
        target_filters = [
            {
                "key": "$feature_flag",
                "value": [flag.key],
                "operator": "exact",
                "type": "event",
            }
        ]

        if exposure_filter:
            entity = exposure_filter.entities[0]
            if entity.id:
                target_entity_type = entity.type if entity.type in ["events", "actions"] else "events"
                target_entity = entity.id
                if entity.type == "actions":
                    try:
                        target_entity = int(target_entity)
                    except ValueError:
                        raise ValidationError("Invalid action ID")

                target_filters = [
                    prop.to_dict()
                    for prop in entity.property_groups.flat
                    if prop.type in ("event", "feature", "element", "hogql")
                ]

        cohort_serializer = CohortSerializer(
            data={
                "is_static": False,
                "name": f'Users exposed to experiment "{experiment.name}"',
                "is_calculating": True,
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "key": target_entity,
                                        "negation": False,
                                        "event_type": target_entity_type,
                                        "event_filters": target_filters,
                                        "explicit_datetime": experiment.start_date.isoformat(),
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
            context={
                "request": request,
                "team": self.team,
                "team_id": self.team_id,
            },
        )

        cohort_serializer.is_valid(raise_exception=True)
        cohort = cohort_serializer.save()
        experiment.exposure_cohort = cohort
        experiment.save(update_fields=["exposure_cohort"])
        return Response({"cohort": cohort_serializer.data}, status=201)

    @action(methods=["GET"], detail=False, required_scopes=["feature_flag:read"])
    def eligible_feature_flags(self, request: Request, **kwargs: Any) -> Response:
        """
        Returns a paginated list of feature flags eligible for use in experiments.

        Eligible flags must:
        - Be multivariate with at least 2 variants
        - Have "control" as the first variant key

        Query parameters:
        - search: Filter by flag key or name (case insensitive)
        - limit: Number of results per page (default: 20)
        - offset: Pagination offset (default: 0)
        - active: Filter by active status ("true" or "false")
        - created_by_id: Filter by creator user ID
        - order: Sort order field
        - evaluation_runtime: Filter by evaluation runtime
        - has_evaluation_tags: Filter by presence of evaluation tags ("true" or "false")
        """
        # validate limit and offset
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response({"error": "Invalid limit or offset"}, status=400)

        queryset = FeatureFlag.objects.filter(team__project_id=self.project_id, deleted=False)

        # Filter for multivariate flags with at least 2 variants and first variant is "control"
        queryset = queryset.extra(
            where=[
                """
                jsonb_array_length(filters->'multivariate'->'variants') >= 2
                AND filters->'multivariate'->'variants'->0->>'key' = 'control'
                """
            ]
        )

        # Exclude survey targeting flags (same as regular feature flag list endpoint)
        survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
        product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
            team__project_id=self.project_id, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
        excluded_flag_ids = survey_flag_ids | set(product_tour_internal_targeting_flags)
        queryset = queryset.exclude(id__in=excluded_flag_ids)

        # Apply search filter
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(Q(key__icontains=search) | Q(name__icontains=search))

        # Apply active filter
        active = request.query_params.get("active")
        if active is not None:
            queryset = queryset.filter(active=active.lower() == "true")

        # Apply created_by filter
        created_by_id = request.query_params.get("created_by_id")
        if created_by_id:
            queryset = queryset.filter(created_by_id=created_by_id)

        # Apply evaluation_runtime filter
        evaluation_runtime = request.query_params.get("evaluation_runtime")
        if evaluation_runtime:
            queryset = queryset.filter(evaluation_runtime=evaluation_runtime)

        # Apply has_evaluation_tags filter
        has_evaluation_tags = request.query_params.get("has_evaluation_tags")
        if has_evaluation_tags is not None:
            from django.db.models import Count

            filter_value = has_evaluation_tags.lower() in ("true", "1", "yes")
            queryset = queryset.annotate(eval_tag_count=Count("evaluation_tags"))
            if filter_value:
                queryset = queryset.filter(eval_tag_count__gt=0)
            else:
                queryset = queryset.filter(eval_tag_count=0)

        # Ordering
        order = request.query_params.get("order")
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-created_at")

        # Prefetch related data to avoid N+1 queries (same as regular feature flag list)
        queryset = queryset.prefetch_related(
            Prefetch(
                "experiment_set", queryset=Experiment.objects.filter(deleted=False), to_attr="_active_experiments"
            ),
            "features",
            "analytics_dashboards",
            "surveys_linked_flag",
            Prefetch(
                "evaluation_tags",
                queryset=FeatureFlagEvaluationTag.objects.select_related("tag"),
            ),
            Prefetch(
                "team__cohort_set",
                queryset=Cohort.objects.filter(deleted=False).only("id", "name"),
                to_attr="available_cohorts",
            ),
        ).select_related("created_by", "last_modified_by")

        total_count = queryset.count()
        results = queryset[offset : offset + limit]

        # Serialize using the standard FeatureFlagSerializer
        serializer = FeatureFlagSerializer(
            results,
            many=True,
            context=self.get_serializer_context(),
        )

        return Response(
            {
                "results": serializer.data,
                "count": total_count,
            }
        )

    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def timeseries_results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Retrieve timeseries results for a specific experiment-metric combination.
        Aggregates daily results into a timeseries format for frontend compatibility.

        Query parameters:
        - metric_uuid (required): The UUID of the metric to retrieve results for
        - fingerprint (required): The fingerprint of the metric configuration
        """
        experiment = self.get_object()
        metric_uuid = request.query_params.get("metric_uuid")
        fingerprint = request.query_params.get("fingerprint")

        if not metric_uuid:
            raise ValidationError("metric_uuid query parameter is required")

        if not fingerprint:
            raise ValidationError("fingerprint query parameter is required")

        project_tz = ZoneInfo(experiment.team.timezone) if experiment.team.timezone else ZoneInfo("UTC")

        if not experiment.start_date:
            raise ValidationError("Experiment has not been started yet")
        start_date = experiment.start_date.date()
        end_date = experiment.end_date.date() if experiment.end_date else date.today()

        experiment_dates = []
        current_date = start_date
        while current_date <= end_date:
            experiment_dates.append(current_date)
            current_date += timedelta(days=1)

        # Pre-populate timeline with null values so frontend gets complete date range
        timeseries: dict[str, Any | None] = {}
        errors: dict[str, str] = {}
        for experiment_date in experiment_dates:
            timeseries[experiment_date.isoformat()] = None

        metric_results = ExperimentMetricResult.objects.filter(
            experiment_id=experiment.id, metric_uuid=metric_uuid, fingerprint=fingerprint
        ).order_by("query_to")

        completed_count = 0
        failed_count = 0
        pending_count = 0
        no_record_count = 0
        latest_completed_at = None

        # Create mapping from query_to to result, deriving the day in project timezone
        # Note: query_to is the EXCLUSIVE end of the time range
        # Example: Data for 2025-11-09 has query_to = 2025-11-10T00:00:00 (recalculation)
        #          or query_to = 2025-11-09T02:00:00 (regular DAG)
        # To find which day the data represents, subtract 1 microsecond to get the last included moment
        results_by_date = {}
        for result in metric_results:
            # Subtract 1 microsecond to convert exclusive boundary to inclusive
            query_to_adjusted = result.query_to - timedelta(microseconds=1)
            query_to_in_project_tz = query_to_adjusted.astimezone(project_tz)
            day_in_project_tz = query_to_in_project_tz.date()
            results_by_date[day_in_project_tz] = result

        for experiment_date in experiment_dates:
            date_key = experiment_date.isoformat()

            if experiment_date in results_by_date:
                metric_result = results_by_date[experiment_date]

                if metric_result.status == "completed":
                    timeseries[date_key] = metric_result.result
                    completed_count += 1
                elif metric_result.status == "failed":
                    if metric_result.error_message:
                        errors[date_key] = metric_result.error_message
                    failed_count += 1
                elif metric_result.status == "pending":
                    pending_count += 1

                if metric_result.completed_at:
                    if latest_completed_at is None or metric_result.completed_at > latest_completed_at:
                        latest_completed_at = metric_result.completed_at
            else:
                no_record_count += 1

        total_experiment_days = len(experiment_dates)
        calculated_days = completed_count + failed_count + pending_count

        # If we have zero calculated days, it's pending
        if calculated_days == 0:
            overall_status = "pending"
        # If all calculated days failed, it's failed
        elif completed_count == 0 and failed_count > 0:
            overall_status = "failed"
        # If we have all days completed, it's completed
        elif completed_count == total_experiment_days:
            overall_status = "completed"
        # If we have at least some data (completed or failed), it's partial
        else:
            overall_status = "partial"

        active_recalculation = ExperimentTimeseriesRecalculation.objects.filter(
            experiment=experiment,
            fingerprint=fingerprint,
            status__in=[
                ExperimentTimeseriesRecalculation.Status.PENDING,
                ExperimentTimeseriesRecalculation.Status.IN_PROGRESS,
            ],
        ).first()

        first_result = metric_results.first()
        last_result = metric_results.last()
        response_data = {
            "experiment_id": experiment.id,
            "metric_uuid": metric_uuid,
            "status": overall_status,
            "timeseries": timeseries,
            "errors": errors if errors else None,
            "computed_at": latest_completed_at.isoformat() if latest_completed_at else None,
            "created_at": first_result.created_at.isoformat() if first_result else experiment.created_at.isoformat(),
            "updated_at": last_result.updated_at.isoformat() if last_result else experiment.updated_at.isoformat(),
            "recalculation_status": active_recalculation.status if active_recalculation else None,
            "recalculation_created_at": active_recalculation.created_at.isoformat() if active_recalculation else None,
        }

        return Response(response_data)

    @action(methods=["POST"], detail=True, required_scopes=["experiment:write"])
    def recalculate_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Create a recalculation request for experiment timeseries data.

        Request body:
        - metric (required): The full metric object to recalculate
        - fingerprint (required): The fingerprint of the metric configuration
        """
        experiment = self.get_object()

        metric = request.data.get("metric")
        fingerprint = request.data.get("fingerprint")

        if not metric:
            raise ValidationError("metric is required")
        if not fingerprint:
            raise ValidationError("fingerprint is required")

        if not experiment.start_date:
            raise ValidationError("Cannot recalculate timeseries for experiment that hasn't started")

        # Check for existing recalculation request to ensure idempotency
        existing_recalculation = ExperimentTimeseriesRecalculation.objects.filter(
            experiment=experiment,
            fingerprint=fingerprint,
            status__in=[
                ExperimentTimeseriesRecalculation.Status.PENDING,
                ExperimentTimeseriesRecalculation.Status.IN_PROGRESS,
            ],
        ).first()

        if existing_recalculation:
            return Response(
                {
                    "id": existing_recalculation.id,
                    "experiment_id": experiment.id,
                    "metric_uuid": existing_recalculation.metric.get("uuid"),
                    "fingerprint": fingerprint,
                    "status": existing_recalculation.status,
                    "created_at": existing_recalculation.created_at.isoformat(),
                },
                status=200,
            )

        # Delete all existing metric results for this experiment/metric/fingerprint combination
        metric_uuid = metric.get("uuid")
        if metric_uuid:
            ExperimentMetricResult.objects.filter(
                experiment_id=experiment.id,
                metric_uuid=metric_uuid,
                fingerprint=fingerprint,
            ).delete()

        # Create new recalculation request
        recalculation_request = ExperimentTimeseriesRecalculation.objects.create(
            team=experiment.team,
            experiment=experiment,
            metric=metric,
            fingerprint=fingerprint,
            status=ExperimentTimeseriesRecalculation.Status.PENDING,
        )

        return Response(
            {
                "id": recalculation_request.id,
                "experiment_id": experiment.id,
                "metric_uuid": metric.get("uuid"),
                "fingerprint": fingerprint,
                "status": recalculation_request.status,
                "created_at": recalculation_request.created_at.isoformat(),
            },
            status=201,
        )

    @action(methods=["GET"], detail=False, url_path="stats", required_scopes=["experiment:read"])
    def stats(self, request: Request, **kwargs: Any) -> Response:
        """Get experimentation velocity statistics."""
        team_tz = ZoneInfo(self.team.timezone) if self.team.timezone else ZoneInfo("UTC")
        today = datetime.now(team_tz).date()

        last_30d_start = today - timedelta(days=30)
        previous_30d_start = today - timedelta(days=60)
        previous_30d_end = last_30d_start

        base_queryset = Experiment.objects.filter(team=self.team, deleted=False, archived=False)

        launched_last_30d = base_queryset.filter(
            start_date__gte=last_30d_start, start_date__lt=today + timedelta(days=1)
        ).count()

        launched_previous_30d = base_queryset.filter(
            start_date__gte=previous_30d_start, start_date__lt=previous_30d_end
        ).count()

        if launched_previous_30d == 0:
            percent_change = 100.0 if launched_last_30d > 0 else 0.0
        else:
            percent_change = ((launched_last_30d - launched_previous_30d) / launched_previous_30d) * 100

        active_experiments = base_queryset.filter(start_date__isnull=False, end_date__isnull=True).count()

        completed_last_30d = base_queryset.filter(
            end_date__gte=last_30d_start, end_date__lt=today + timedelta(days=1)
        ).count()

        return Response(
            {
                "launched_last_30d": launched_last_30d,
                "launched_previous_30d": launched_previous_30d,
                "percent_change": round(percent_change, 1),
                "active_experiments": active_experiments,
                "completed_last_30d": completed_last_30d,
            }
        )


@mutable_receiver(model_activity_signal, sender=Experiment)
def handle_experiment_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    if before_update and after_update:
        before_deleted = getattr(before_update, "deleted", None)
        after_deleted = getattr(after_update, "deleted", None)
        if before_deleted is not None and after_deleted is not None and before_deleted != after_deleted:
            activity = "restored" if after_deleted is False else "deleted"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update), name=after_update.name
        ),
    )
