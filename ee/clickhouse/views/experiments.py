from typing import Any, Optional
from collections.abc import Callable

from django.utils.timezone import now
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from statshog.defaults.django import statsd
import posthoganalytics

from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    ClickhouseFunnelExperimentResult,
)
from ee.clickhouse.queries.experiments.secondary_experiment_result import (
    ClickhouseSecondaryExperimentResult,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import (
    ClickhouseTrendExperimentResult,
)
from ee.clickhouse.queries.experiments.utils import requires_flag_warning
from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.caching.insight_cache import update_cached_state
from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import INSIGHT_TRENDS
from posthog.models.experiment import Experiment
from posthog.models.filters.filter import Filter
from posthog.utils import generate_cache_key, get_safe_cache

EXPERIMENT_RESULTS_CACHE_DEFAULT_TTL = 60 * 60  # 1 hour


def _calculate_experiment_results(experiment: Experiment, refresh: bool = False):
    # :TRICKY: Don't run any filter simplification on the experiment filter yet
    filter = Filter({**experiment.filters, "is_simplified": True}, team=experiment.team)

    exposure_filter_data = (experiment.parameters or {}).get("custom_exposure_filter")
    exposure_filter = None
    if exposure_filter_data:
        exposure_filter = Filter(data={**exposure_filter_data, "is_simplified": True}, team=experiment.team)

    if filter.insight == INSIGHT_TRENDS:
        calculate_func = lambda: ClickhouseTrendExperimentResult(
            filter,
            experiment.team,
            experiment.feature_flag,
            experiment.start_date,
            experiment.end_date,
            custom_exposure_filter=exposure_filter,
        ).get_results()
    else:
        calculate_func = lambda: ClickhouseFunnelExperimentResult(
            filter,
            experiment.team,
            experiment.feature_flag,
            experiment.start_date,
            experiment.end_date,
        ).get_results()

    return _experiment_results_cached(
        experiment,
        "primary",
        filter,
        calculate_func,
        refresh=refresh,
        exposure_filter=exposure_filter,
    )


def _calculate_secondary_experiment_results(experiment: Experiment, parsed_id: int, refresh: bool = False):
    filter = Filter(experiment.secondary_metrics[parsed_id]["filters"], team=experiment.team)

    calculate_func = lambda: ClickhouseSecondaryExperimentResult(
        filter,
        experiment.team,
        experiment.feature_flag,
        experiment.start_date,
        experiment.end_date,
    ).get_results()
    return _experiment_results_cached(experiment, "secondary", filter, calculate_func, refresh=refresh)


def _experiment_results_cached(
    experiment: Experiment,
    results_type: str,
    filter: Filter,
    calculate_func: Callable,
    refresh: bool,
    exposure_filter: Optional[Filter] = None,
):
    cache_filter = filter.shallow_clone(
        {
            "date_from": experiment.start_date,
            "date_to": experiment.end_date if experiment.end_date else None,
        }
    )

    exposure_suffix = "" if not exposure_filter else f"_{exposure_filter.toJSON()}"

    cache_key = generate_cache_key(
        f"experiment_{results_type}_{cache_filter.toJSON()}_{experiment.team.pk}_{experiment.pk}{exposure_suffix}"
    )

    tag_queries(cache_key=cache_key)

    cached_result_package = get_safe_cache(cache_key)

    if cached_result_package and cached_result_package.get("result") and not refresh:
        cached_result_package["is_cached"] = True
        statsd.incr(
            "posthog_cached_function_cache_hit",
            tags={"route": "/projects/:id/experiments/:experiment_id/results"},
        )
        return cached_result_package

    statsd.incr(
        "posthog_cached_function_cache_miss",
        tags={"route": "/projects/:id/experiments/:experiment_id/results"},
    )

    result = calculate_func()

    timestamp = now()
    fresh_result_package = {"result": result, "last_refresh": now(), "is_cached": False}

    # Event to detect experiment significance flip-flopping
    posthoganalytics.capture(
        experiment.created_by.email,
        "experiment result calculated",
        properties={
            "experiment_id": experiment.id,
            "name": experiment.name,
            "goal_type": experiment.filters.get("insight", "FUNNELS"),
            "significant": result.get("significant"),
            "significance_code": result.get("significance_code"),
            "probability": result.get("probability"),
        },
    )

    update_cached_state(
        experiment.team.pk,
        cache_key,
        timestamp,
        fresh_result_package,
        ttl=EXPERIMENT_RESULTS_CACHE_DEFAULT_TTL,
    )

    return fresh_result_package


class ExperimentSerializer(serializers.ModelSerializer):
    feature_flag_key = serializers.CharField(source="get_feature_flag_key")
    created_by = UserBasicSerializer(read_only=True)
    feature_flag = MinimalFeatureFlagSerializer(read_only=True)

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
            "exposure_cohort",
            "parameters",
            "secondary_metrics",
            "filters",
            "archived",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "feature_flag",
            "exposure_cohort",
        ]

    def validate_parameters(self, value):
        if not value:
            return value

        variants = value.get("feature_flag_variants", [])

        if len(variants) >= 11:
            raise ValidationError("Feature flag variants must be less than 11")
        elif len(variants) > 0:
            if "control" not in [variant["key"] for variant in variants]:
                raise ValidationError("Feature flag variants must contain a control variant")

        return value

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        if not validated_data.get("filters"):
            raise ValidationError("Filters are required to create an Experiment")

        variants = []
        aggregation_group_type_index = None
        if validated_data["parameters"]:
            variants = validated_data["parameters"].get("feature_flag_variants", [])
            aggregation_group_type_index = validated_data["parameters"].get("aggregation_group_type_index")

        request = self.context["request"]
        validated_data["created_by"] = request.user

        feature_flag_key = validated_data.pop("get_feature_flag_key")

        is_draft = "start_date" not in validated_data or validated_data["start_date"] is None

        properties = validated_data["filters"].get("properties", [])

        if properties:
            raise ValidationError("Experiments do not support global filter properties")

        default_variants = [
            {"key": "control", "name": "Control Group", "rollout_percentage": 50},
            {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
        ]

        filters = {
            "groups": [{"properties": properties, "rollout_percentage": 100}],
            "multivariate": {"variants": variants or default_variants},
            "aggregation_group_type_index": aggregation_group_type_index,
        }

        feature_flag_serializer = FeatureFlagSerializer(
            data={
                "key": feature_flag_key,
                "name": f'Feature Flag for Experiment {validated_data["name"]}',
                "filters": filters,
                "active": not is_draft,
            },
            context=self.context,
        )

        feature_flag_serializer.is_valid(raise_exception=True)
        feature_flag = feature_flag_serializer.save()

        experiment = Experiment.objects.create(
            team_id=self.context["team_id"], feature_flag=feature_flag, **validated_data
        )
        return experiment

    def update(self, instance: Experiment, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
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
            "secondary_metrics",
        }
        given_keys = set(validated_data.keys())
        extra_keys = given_keys - expected_keys

        if feature_flag.key == validated_data.get("get_feature_flag_key"):
            extra_keys.remove("get_feature_flag_key")

        if extra_keys:
            raise ValidationError(f"Can't update keys: {', '.join(sorted(extra_keys))} on Experiment")

        # if an experiment has launched, we cannot edit its variants anymore.
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

        properties = validated_data.get("filters", {}).get("properties")
        if properties:
            raise ValidationError("Experiments do not support global filter properties")

        if instance.is_draft:
            # if feature flag variants have changed, update the feature flag.
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

                filters = {
                    "groups": [{"properties": properties, "rollout_percentage": 100}],
                    "multivariate": {"variants": variants or default_variants},
                    "aggregation_group_type_index": aggregation_group_type_index,
                }

                existing_flag_serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={"filters": filters},
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


class ClickhouseExperimentsViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    serializer_class = ExperimentSerializer
    queryset = Experiment.objects.prefetch_related("feature_flag", "created_by").all()
    ordering = "-created_at"

    # ******************************************
    # /projects/:id/experiments/:experiment_id/results
    #
    # Returns current results of an experiment, and graphs
    # 1. Probability of success
    # 2. Funnel breakdown graph to display
    # ******************************************
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: Experiment = self.get_object()

        refresh = request.query_params.get("refresh") is not None

        if not experiment.filters:
            raise ValidationError("Experiment has no target metric")

        result = _calculate_experiment_results(experiment, refresh)

        return Response(result)

    # ******************************************
    # /projects/:id/experiments/:experiment_id/secondary_results?id=<secondary_metric_id>
    #
    # Returns values for secondary experiment metrics, broken down by variants
    # ******************************************
    @action(methods=["GET"], detail=True, required_scopes=["experiment:read"])
    def secondary_results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: Experiment = self.get_object()

        refresh = request.query_params.get("refresh") is not None

        if not experiment.secondary_metrics:
            raise ValidationError("Experiment has no secondary metrics")

        metric_id = request.query_params.get("id")

        if not metric_id:
            raise ValidationError("Secondary metric id is required")

        try:
            parsed_id = int(metric_id)
        except ValueError:
            raise ValidationError("Secondary metric id must be an integer")

        if parsed_id > len(experiment.secondary_metrics):
            raise ValidationError("Invalid metric ID")

        result = _calculate_secondary_experiment_results(experiment, parsed_id, refresh)

        return Response(result)

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
