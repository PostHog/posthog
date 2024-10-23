from typing import Any
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from django.db import transaction


from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.experiment import ExperimentHoldout


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

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ExperimentHoldout:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        if not validated_data.get("filters"):
            raise ValidationError("Filters are required to create an holdout group")

        return super().create(validated_data)

    def update(self, instance: ExperimentHoldout, validated_data):
        filters = validated_data.get("filters")
        if filters and instance.filters != filters:
            # update flags on all experiments in this holdout group
            with transaction.atomic():
                for experiment in instance.experiment_set.all():
                    flag = experiment.feature_flag
                    existing_flag_serializer = FeatureFlagSerializer(
                        flag,
                        data={"filters": {**flag.filters, "holdout_groups": validated_data["filters"]}},
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
