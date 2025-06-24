from enum import Enum
from typing import Any, Literal

from django.db.models import Q, QuerySet
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.experiments.utils import requires_flag_warning
from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutSerializer
from ee.clickhouse.views.experiment_saved_metrics import (
    ExperimentToSavedMetricSerializer,
)
from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentSavedMetric,
)
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team.team import Team
from posthog.schema import ExperimentEventExposureConfig


class ExperimentSerializer(serializers.ModelSerializer):
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

    def validate_metrics(self, value):
        # TODO 2024-11-15: commented code will be addressed when persistent metrics are implemented.

        return value

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
            try:
                ExperimentEventExposureConfig.model_validate(exposure_criteria["exposure_config"])
                return exposure_criteria
            except Exception:
                raise ValidationError("Invalid exposure criteria")

        return exposure_criteria

    def validate(self, data):
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Only validate if both dates are present
        if start_date and end_date and start_date >= end_date:
            raise ValidationError("End date must be after start date")

        return data

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        is_draft = "start_date" not in validated_data or validated_data["start_date"] is None

        # if not validated_data.get("filters") and not is_draft:
        #     raise ValidationError("Filters are required when creating a launched experiment")

        saved_metrics_data = validated_data.pop("saved_metrics_ids", [])

        variants = []
        aggregation_group_type_index = None
        if validated_data["parameters"]:
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
            if validated_data.get("_create_in_folder") is not None:
                feature_flag_data["_create_in_folder"] = validated_data["_create_in_folder"]
            feature_flag_serializer = FeatureFlagSerializer(
                data=feature_flag_data,
                context=self.context,
            )

            feature_flag_serializer.is_valid(raise_exception=True)
            feature_flag = feature_flag_serializer.save()

        if not validated_data.get("stats_config"):
            # Get organization's default stats method setting
            team = Team.objects.get(id=self.context["team_id"])
            default_method = team.organization.default_experiment_stats_method
            validated_data["stats_config"] = {"method": default_method}

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


class EnterpriseExperimentsViewSet(ForbidDestroyModel, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
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
