"""DRF serializers for agentic_tests."""

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
            "duration_ms",
            "output",
            "error_message",
            "external_session_id",
            "screenshot_url",
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
            "source_replay_id",
            "created_by",
            "created_at",
            "updated_at",
            "last_run_at",
            "last_run",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "last_run_at",
            "last_run",
        ]

    def get_last_run(self, obj: AgenticTest) -> dict | None:
        run = obj.runs.order_by("-started_at").first()
        if run is None:
            return None
        return AgenticTestRunSerializer(run).data
