"""DRF serializers for agentic_tests."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun


class AgenticTestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgenticTestRun
        fields = [
            "id",
            "agentic_test",
            "started_at",
            "finished_at",
            "status",
            "source",
            "duration_ms",
            "output",
            "error_message",
            "external_session_id",
            "screenshot_url",
            "region",
            "posthog_session_id",
            "log_entries",
        ]
        read_only_fields = fields


class AgenticTestSerializer(serializers.ModelSerializer):
    last_run = serializers.SerializerMethodField(
        help_text="Most recent run for this test, or null if none have completed yet."
    )
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = AgenticTest
        fields = [
            "id",
            "name",
            "description",
            "target_url",
            "prompt",
            "status",
            "assertions",
            "schedule_cron",
            "regions",
            "next_run_at",
            "source_replay_id",
            "created_by",
            "created_at",
            "updated_at",
            "last_run_at",
            "last_run",
        ]
        read_only_fields = [
            "id",
            "next_run_at",
            "created_by",
            "created_at",
            "updated_at",
            "last_run_at",
            "last_run",
        ]

    @extend_schema_field(AgenticTestRunSerializer(allow_null=True))
    def get_last_run(self, obj: AgenticTest) -> dict | None:
        run = obj.runs.order_by("-started_at").first()
        if run is None:
            return None
        return AgenticTestRunSerializer(run).data


class DetectFlowsRequestSerializer(serializers.Serializer):
    repository = serializers.CharField(
        max_length=256,
        help_text="GitHub repository in 'owner/repo' format, e.g. 'posthog/posthog-js'.",
    )
    domain = serializers.CharField(
        max_length=256,
        help_text="Domain where the product is deployed, e.g. 'us.posthog.com'.",
    )


class DetectFlowsResponseSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="ID of the created task.")
    task_run_id = serializers.UUIDField(allow_null=True, help_text="ID of the task run to stream logs from.")
    status = serializers.CharField(
        allow_null=True,
        required=False,
        default=None,
        help_text="Current status of the task run: queued, in_progress, completed, failed, or cancelled.",
    )
