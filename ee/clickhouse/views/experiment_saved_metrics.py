from django.db.models.functions import Lower
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService

from ee.api.rbac.access_control import AccessControlViewSetMixin


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


class ExperimentSavedMetricSerializer(
    UserAccessControlSerializerMixin, TaggedItemSerializerMixin, serializers.ModelSerializer
):
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
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "user_access_level",
        ]

    def create(self, validated_data):
        tags = validated_data.pop("tags", None)
        name = validated_data.pop("name")
        query = validated_data.pop("query")
        description = validated_data.pop("description", None)

        if validated_data:
            raise serializers.ValidationError(
                f"Can't create keys: {', '.join(sorted(validated_data))} on ExperimentSavedMetric"
            )

        service = self._build_service()
        instance = service.create_saved_metric(name=name, query=query, description=description)
        self._attempt_set_tags(tags, instance)
        return instance

    def update(self, instance: ExperimentSavedMetric, validated_data):
        tags = validated_data.pop("tags", None)
        service = self._build_service()
        instance = service.update_saved_metric(instance, validated_data)
        self._attempt_set_tags(tags, instance)
        return instance

    def _build_service(self) -> ExperimentSavedMetricService:
        request = self.context["request"]
        return ExperimentSavedMetricService(team=self.context["get_team"](), user=request.user)


@extend_schema(tags=["experiments"])
class ExperimentSavedMetricViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment_saved_metric"
    queryset = ExperimentSavedMetric.objects.prefetch_related("created_by").order_by(Lower("name")).all()
    serializer_class = ExperimentSavedMetricSerializer

    def perform_destroy(self, instance: ExperimentSavedMetric) -> None:
        service = ExperimentSavedMetricService(team=self.team, user=self.request.user)
        service.delete_saved_metric(instance)


@mutable_receiver(model_activity_signal, sender=ExperimentSavedMetric)
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
