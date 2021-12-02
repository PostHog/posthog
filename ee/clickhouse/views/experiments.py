from typing import Any

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries import experiments
from ee.clickhouse.queries.experiments.funnel_experiment_result import ClickhouseFunnelExperimentResult
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.experiment import Experiment
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class ExperimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Experiment
        fields = ["id", "name", "description", "start_date", "end_date", "feature_flag", "filters"]


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
            experiment.filters, self.team, experiment.feature_flag, experiment.start_date, experiment.end_date
        ).get_results()
        return Response(result)
