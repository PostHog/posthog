from django.db.models.functions import Lower
from django.db.models.signals import pre_delete
from django.dispatch import receiver

import pydantic
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentFunnelsQuery,
    ExperimentMeanMetric,
    ExperimentMetricType,
    ExperimentRatioMetric,
    ExperimentTrendsQuery,
)

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric
from posthog.models.signals import model_activity_signal


class ExperimentToSavedMetricSerializer(serializers.ModelSerializer):
    query = serializers.JSONField(source="saved_metric.query", read_only=True)
    name = serializers.CharField(source="saved_metric.name", read_only=True)

    class Meta:
        model = ExperimentToSavedMetric
        fields = [
            "id",
            "experiment",
            "saved_metric",
            "metadata",
            "created_at",
            "query",
            "name",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]


class ExperimentSavedMetricSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ExperimentSavedMetric
        fields = [
            "id",
            "name",
            "description",
            "query",
            "created_by",
            "created_at",
            "updated_at",
            "tags",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_query(self, value):
        if not value:
            raise ValidationError("Query is required to create a saved metric")

        metric_query = value

        if metric_query.get("kind") not in ["ExperimentMetric", "ExperimentTrendsQuery", "ExperimentFunnelsQuery"]:
            raise ValidationError(
                "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'"
            )

        # pydantic models are used to validate the query
        try:
            if metric_query["kind"] == "ExperimentMetric":
                if "metric_type" not in metric_query:
                    raise ValidationError("ExperimentMetric requires a metric_type")
                if metric_query["metric_type"] == ExperimentMetricType.MEAN:
                    ExperimentMeanMetric(**metric_query)
                elif metric_query["metric_type"] == ExperimentMetricType.FUNNEL:
                    ExperimentFunnelMetric(**metric_query)
                elif metric_query["metric_type"] == ExperimentMetricType.RATIO:
                    ExperimentRatioMetric(**metric_query)
                else:
                    raise ValidationError("ExperimentMetric metric_type must be 'mean', 'funnel', or 'ratio'")
            elif metric_query["kind"] == "ExperimentTrendsQuery":
                ExperimentTrendsQuery(**metric_query)
            elif metric_query["kind"] == "ExperimentFunnelsQuery":
                ExperimentFunnelsQuery(**metric_query)
        except pydantic.ValidationError as e:
            raise ValidationError(str(e.errors())) from e

        return value

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)


class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    queryset = ExperimentSavedMetric.objects.prefetch_related("created_by").order_by(Lower("name")).all()
    serializer_class = ExperimentSavedMetricSerializer


@receiver(model_activity_signal, sender=ExperimentSavedMetric)
def handle_experiment_saved_metric_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope="Experiment",  # log under Experiment scope so it appears in experiment activity log
        activity=activity,
        detail=Detail(
            # need to use ExperimentSavedMetric here for field exclusions..
            changes=changes_between("ExperimentSavedMetric", previous=before_update, current=after_update),
            name=after_update.name,
            type="shared_metric",
        ),
    )


@receiver(pre_delete, sender=ExperimentSavedMetric)
def handle_experiment_saved_metric_delete(sender, instance, **kwargs):
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=getattr(instance, "last_modified_by", instance.created_by),
        was_impersonated=False,
        item_id=instance.id,
        scope="Experiment",  # log under Experiment scope so it appears in experiment activity log
        activity="deleted",
        detail=Detail(name=instance.name, type="shared_metric"),
    )
