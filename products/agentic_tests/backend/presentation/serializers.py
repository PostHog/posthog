"""DRF serializers for agentic_tests."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun


class AgenticTestRunSerializer(serializers.ModelSerializer):
    investigation_conversation_id = serializers.SerializerMethodField(
        help_text="ID of the PostHog AI conversation investigating this failure, if one exists."
    )

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
            "investigation_conversation_id",
        ]
        read_only_fields = fields

    def get_investigation_conversation_id(self, run: AgenticTestRun) -> str | None:
        # Use the batch-computed lookup from context (set by the viewset's list method)
        # to avoid N+1 queries. Falls back to a per-row query for detail endpoints.
        lookup: dict[str, str] | None = self.context.get("investigation_lookup")
        if lookup is not None:
            return lookup.get(str(run.id))
        return self._lookup_investigation_for_run(run)

    @staticmethod
    def _lookup_investigation_for_run(run: AgenticTestRun) -> str | None:
        from ee.models.assistant import Conversation

        run_id = str(run.id)
        for conv in (
            Conversation.objects.filter(
                team_id=run.agentic_test.team_id,
                sandbox_task_id__isnull=False,
                messages_json__isnull=False,
            )
            .only("id", "messages_json")
            .order_by("-created_at")[:50]
        ):
            messages = conv.messages_json
            if not messages or not isinstance(messages, list):
                continue
            first = messages[0]
            if not isinstance(first, dict):
                continue
            if run_id in first.get("_meta", {}).get("signal_source_ids", []):
                return str(conv.id)
        return None

    @staticmethod
    def build_investigation_lookup(team_id: int, run_ids: list[str]) -> dict[str, str]:
        """Batch-compute run_id -> conversation_id mapping for a set of runs."""
        from ee.models.assistant import Conversation

        if not run_ids:
            return {}
        lookup: dict[str, str] = {}
        remaining = set(run_ids)
        for conv in (
            Conversation.objects.filter(
                team_id=team_id,
                sandbox_task_id__isnull=False,
                messages_json__isnull=False,
            )
            .only("id", "messages_json")
            .order_by("-created_at")[:50]
        ):
            messages = conv.messages_json
            if not messages or not isinstance(messages, list):
                continue
            first = messages[0]
            if not isinstance(first, dict):
                continue
            source_ids = first.get("_meta", {}).get("signal_source_ids", [])
            for sid in source_ids:
                if sid in remaining:
                    lookup[sid] = str(conv.id)
                    remaining.discard(sid)
            if not remaining:
                break
        return lookup


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
