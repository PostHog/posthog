from rest_framework import serializers
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording import ClickhouseSessionRecording
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from posthog.api.session_recording import SessionRecordingViewSet
from posthog.models.experiment import Experiment


class ExperimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Experiment
        fields = ["id", "name", "description", "feature_flags", "filters"]

class ClickhouseExperimentsViewSet(SessionRecordingViewSet):
    serializer_class = ExperimentSerializer
    queryset = Experiment.objects.all()
    
    def get_queryset(self):
        return super().get_queryset()
    