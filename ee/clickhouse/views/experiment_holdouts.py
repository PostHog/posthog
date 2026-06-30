from typing import Any

from django.db import transaction

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import FeatureFlagConditionGroupSchemaSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.experiments.backend.models.experiment import ExperimentHoldout, holdout_filters_for_flag
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer


@extend_schema_field(FeatureFlagConditionGroupSchemaSerializer(many=True))
class HoldoutFiltersField(serializers.JSONField):
    """JSONField typed as a list of feature-flag release-condition groups for OpenAPI generation.

    Documentation-only — the runtime stays a plain JSONField, so `validate_filters` and the
    server-managed `variant` normalization are unaffected.
    """

    pass


class ExperimentHoldoutSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """A holdout group — a stable slice of users excluded from experiment exposure."""

    created_by = UserBasicSerializer(read_only=True)
    # Declared explicitly only to attach the typed schema; `required=False` mirrors the model's
    # JSONField default. Help text for name/description is added via Meta.extra_kwargs so the
    # model-derived constraints (e.g. max_length) are preserved.
    filters = HoldoutFiltersField(
        required=False,
        help_text=(
            "Non-empty list of release-condition groups defining the held-out population, using the same shape as "
            "feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the "
            "**exclusion** percentage — the share of users held back from all experiments that reference this holdout. "
            "`properties` optionally narrows the group by person/group properties. Do not set `variant`: the server "
            "normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into "
            "each linked experiment's feature flag, and this population is shared across every experiment using the "
            "holdout."
        ),
    )

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
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "user_access_level",
        ]
        extra_kwargs = {
            "name": {"help_text": "Human-readable name for the holdout group."},
            "description": {"help_text": "Optional description of what this holdout reserves and why."},
        }

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
        if not filters:
            raise serializers.ValidationError("Filters must not be empty.")

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
                            "filters": {
                                **flag.filters,
                                **holdout_filters_for_flag(instance.id, validated_data["filters"]),
                            },
                        },
                        partial=True,
                        context=self.context,
                    )
                    existing_flag_serializer.is_valid(raise_exception=True)
                    existing_flag_serializer.save()
                return super().update(instance, validated_data)

        return super().update(instance, validated_data)


@extend_schema(extensions={"x-swagger-tag": "experiment_holdouts", "x-product": "experiments"})
class ExperimentHoldoutViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    # Deliberately NOT an AccessControlViewSetMixin: holdouts are shared project config that
    # inherit experiment access, with no per-holdout grants. Exposing `/{id}/access_controls`
    # would let an object-level holdout grant bypass resource-level experiment access.
    scope_object = "experiment_holdout"
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
                            **holdout_filters_for_flag(None, None),
                        }
                    },
                    partial=True,
                    context={"request": request, "team": self.team, "team_id": self.team_id},
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                existing_flag_serializer.save()

            return super().destroy(request, *args, **kwargs)
