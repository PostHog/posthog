from typing import Any

from rest_framework import request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.experiments.funnel_experiment_result import ClickhouseFunnelExperimentResult
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class ExperimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Experiment
        fields = [
            "id",
            "name",
            "description",
            "start_date",
            "end_date",
            "feature_flag",
            "parameters",
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

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Experiment:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        team = Team.objects.get(id=self.context["team_id"])

        # feature_flag = FeatureFlag.objects.filter(key=validated_data["feature_flag"], team_id=self.context["team_id"], deleted=False).first()
        # validated_data["feature_flag"] = feature_flag.pk

        experiment = Experiment.objects.create(team=team, **validated_data)
        return experiment


class ClickhouseExperimentsViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ExperimentSerializer
    queryset = Experiment.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self):
        return super().get_queryset()

    # ******************************************
    # /projects/:id/experiments/:experiment_id/results
    #
    # Returns current results of an experiment, and graphs
    #  1. Probability of success
    # 2. Funnel breakdown graph to display
    # 3. (?): Histogram of possible values - bucketed on backend
    # ******************************************
    @action(methods=["GET"], detail=True)
    def results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        experiment: Experiment = self.get_object()

        if not experiment.filters:
            raise ValidationError("Experiment has no target metric")

        result = ClickhouseFunnelExperimentResult(
            Filter(experiment.filters),
            self.team,
            experiment.feature_flag.key,
            experiment.start_date,
            experiment.end_date,
        ).get_results()
        return Response(result)
