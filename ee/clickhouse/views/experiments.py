from rest_framework import serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.experiment import Experiment


class ExperimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Experiment
        fields = ["id", "name", "description", "feature_flags", "filters"]


class ClickhouseExperimentsView(StructuredViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ExperimentSerializer
    queryset = Experiment.objects.all()

    def get_queryset(self):
        return super().get_queryset()
