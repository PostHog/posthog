from typing import Any

from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.experiment import ExperimentHoldout
from posthog.models.signals import model_activity_signal


class ExperimentHoldoutSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ExperimentHoldout
        fields = [
            "id",
            "name",
            "description",
            "filters",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def _get_filters_with_holdout_id(self, id: int, filters: list) -> list:
        variant_key = f"holdout-{id}"
        updated_filters = []
        for filter in filters:
            updated_filters.append(
                {
                    **filter,
                    "variant": variant_key,
                }
            )
        return updated_filters

    def validate_filters(self, filters):
        for filter in filters:
            rollout_percentage = filter.get("rollout_percentage")
            if rollout_percentage is None:
                raise serializers.ValidationError("Rollout percentage must be present.")
            if rollout_percentage < 0 or rollout_percentage > 100:
                raise serializers.ValidationError("Rollout percentage must be between 0 and 100.")

        return filters

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ExperimentHoldout:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        if not validated_data.get("filters"):
            raise ValidationError("Filters are required to create an holdout group")

        instance = super().create(validated_data)
        instance.filters = self._get_filters_with_holdout_id(instance.id, instance.filters)
        instance.save(skip_activity_log=True)  # Skip activity logging for filters update
        return instance

    def update(self, instance: ExperimentHoldout, validated_data):
        filters = validated_data.get("filters")
        if filters and instance.filters != filters:
            # update flags on all experiments in this holdout group
            new_filters = self._get_filters_with_holdout_id(instance.id, filters)
            validated_data["filters"] = new_filters
            with transaction.atomic():
                for experiment in instance.experiment_set.all():
                    flag = experiment.feature_flag
                    existing_flag_serializer = FeatureFlagSerializer(
                        flag,
                        data={
                            "filters": {**flag.filters, "holdout_groups": validated_data["filters"]},
                        },
                        partial=True,
                        context=self.context,
                    )
                    existing_flag_serializer.is_valid(raise_exception=True)
                    existing_flag_serializer.save()

        return super().update(instance, validated_data)


class ExperimentHoldoutViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    queryset = ExperimentHoldout.objects.prefetch_related("created_by").all()
    serializer_class = ExperimentHoldoutSerializer
    ordering = "-created_at"

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        with transaction.atomic():
            for experiment in instance.experiment_set.all():
                flag = experiment.feature_flag
                existing_flag_serializer = FeatureFlagSerializer(
                    flag,
                    data={
                        "filters": {
                            **flag.filters,
                            "holdout_groups": None,
                        }
                    },
                    partial=True,
                    context={"request": request, "team": self.team, "team_id": self.team_id},
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                existing_flag_serializer.save()

        return super().destroy(request, *args, **kwargs)


@receiver(model_activity_signal, sender=ExperimentHoldout)
def handle_experiment_holdout_change(
    sender, scope, before_update, after_update, activity, user=None, was_impersonated=False, **kwargs
):
    # Log activity for the holdout itself
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user or after_update.created_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope="Experiment",  # log under Experiment scope so it appears in experiment activity log
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
            type="holdout",
        ),
    )


@receiver(pre_delete, sender=ExperimentHoldout)
def handle_experiment_holdout_delete(sender, instance, **kwargs):
    from posthog.models.activity_logging.utils import activity_storage

    # Log activity for the holdout itself
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=activity_storage.get_user() or getattr(instance, "last_modified_by", instance.created_by),
        was_impersonated=activity_storage.get_was_impersonated(),
        item_id=instance.id,
        scope="Experiment",
        activity="deleted",
        detail=Detail(name=instance.name, type="holdout"),
    )
