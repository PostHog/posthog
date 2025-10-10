from copy import deepcopy
from datetime import date, timedelta
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from django.db.models import Case, F, Q, QuerySet, Value, When
from django.db.models.functions import Now
from django.dispatch import receiver

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
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.experiment import Experiment, ExperimentHoldout, ExperimentMetricResult, ExperimentSavedMetric
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.signals import model_activity_signal
from posthog.models.team.team import Team
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

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
                    instance.stats_config,
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

        # check if all saved metrics exist
        saved_metrics = ExperimentSavedMetric.objects.filter(id__in=[saved_metric["id"] for saved_metric in value])
        if saved_metrics.count() != len(value):
            raise ValidationError("Saved metric does not exist")

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
                    metric["fingerprint"] = compute_metric_fingerprint(
                        metric, validated_data.get("start_date"), stats_config, validated_data.get("exposure_criteria")
                    )

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
                # TODO: Going the above route means we can still sometimes fail when validation fails?
                # But this shouldn't really happen, if it does its a bug in our validation logic (validate_saved_metrics_ids)
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
                    metric_copy["fingerprint"] = compute_metric_fingerprint(
                        metric_copy,
                        start_date,
                        stats_config,
                        exposure_criteria,
                    )
                    updated_metrics.append(metric_copy)

                validated_data[metric_field] = updated_metrics

        if instance.is_draft and has_start_date:
            feature_flag.active = True
            feature_flag.save()
            return super().update(instance, validated_data)
        else:
            # Not a draft, doesn't have start date
            # Or draft without start date
            return super().update(instance, validated_data)


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
            "parameters": source_experiment.parameters,
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
        results_by_date = {}
        for result in metric_results:
            # Convert UTC query_to to project timezone to determine which day this result belongs to
            day_in_project_tz = result.query_to.astimezone(project_tz).date()
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
        }

        return Response(response_data)


@receiver(model_activity_signal, sender=Experiment)
def handle_experiment_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
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
