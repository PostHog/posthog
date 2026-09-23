from typing import Any

from django.db import transaction

from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import FeatureFlagConditionGroupSchemaSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.approvals.backend.decorators import approval_gate
from products.approvals.backend.mixins import ApprovalHandlingMixin
from products.experiments.backend.models.experiment import ExperimentHoldout
from products.feature_flags.backend.facade.api import update_flag
from products.feature_flags.backend.facade.filters import set_holdout

# A holdout change is gated as one operation, so the flag writes it fans out into must not
# re-enter the flag gate: a second gate inside the transaction would roll its own change
# request back. See products/approvals/backend/actions/experiment_holdouts.py.
HOLDOUT_GATED_AT_OPERATION = {"approval_apply": True}


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

    @approval_gate("experiment_holdout.update")
    def update(self, instance: ExperimentHoldout, validated_data):
        filters = validated_data.get("filters")
        if filters and instance.filters != filters:
            # update flags on all experiments in this holdout group
            new_filters = self._get_filters_with_holdout_id(instance.id, filters)
            validated_data["filters"] = new_filters
            with transaction.atomic():
                for experiment in instance.experiment_set.all():
                    flag = experiment.feature_flag
                    update_flag(
                        flag,
                        {
                            "filters": set_holdout(
                                flag.filters,
                                holdout_id=instance.id,
                                # validate_filters guarantees a non-empty list with rollout_percentage present.
                                exclusion_percentage=new_filters[0]["rollout_percentage"],
                            ),
                        },
                        team=self.context["get_team"](),
                        user=self.context["request"].user,
                        request=self.context["request"],
                        serializer_context={**self.context, **HOLDOUT_GATED_AT_OPERATION},
                    )
                return super().update(instance, validated_data)

        return super().update(instance, validated_data)


def delete_holdout_and_clear_flags(holdout: ExperimentHoldout, *, user: Any, request: Any = None) -> None:
    """Delete a holdout and drop its exclusion from every linked experiment's flag.

    Shared by the endpoint and by the apply path of an approved delete, so both write the same
    rows in the same transaction.
    """
    with transaction.atomic():
        for experiment in holdout.experiment_set.all():
            flag = experiment.feature_flag
            update_flag(
                flag,
                {"filters": set_holdout(flag.filters, holdout_id=None, exclusion_percentage=None)},
                team=holdout.team,
                user=user,
                request=request,
                serializer_context=HOLDOUT_GATED_AT_OPERATION,
            )
        holdout.delete()


@extend_schema(extensions={"x-swagger-tag": "experiment_holdouts", "x-product": "experiments"})
class ExperimentHoldoutViewSet(ApprovalHandlingMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete experiment holdouts.
    """

    # Deliberately NOT an AccessControlViewSetMixin: holdouts are shared project config that
    # inherit experiment access, with no per-holdout grants. Exposing `/{id}/access_controls`
    # would let an object-level holdout grant bypass resource-level experiment access.
    scope_object = "experiment_holdout"
    queryset = ExperimentHoldout.objects.prefetch_related("created_by").all()
    serializer_class = ExperimentHoldoutSerializer
    ordering = "-created_at"

    @approval_gate("experiment_holdout.delete")
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        delete_holdout_and_clear_flags(self.get_object(), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
