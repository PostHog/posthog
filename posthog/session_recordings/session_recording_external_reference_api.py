from typing import Any

from django.conf import settings

import structlog
import posthoganalytics
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models.integration import (
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_external_reference import SessionRecordingExternalReference

logger = structlog.get_logger(__name__)


class SessionRecordingExternalReferenceIntegrationSerializer(serializers.ModelSerializer):
    """Read-only serializer for Integration info embedded in external references"""

    class Meta:
        model = Integration
        fields = ["id", "kind", "display_name"]
        read_only_fields = ["id", "kind", "display_name"]


class SessionRecordingExternalReferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for linking session recordings to external issue trackers.
    Reuses error tracking's integration infrastructure
    """

    config = serializers.JSONField(write_only=True)
    session_recording_id = serializers.CharField(write_only=True)
    integration = SessionRecordingExternalReferenceIntegrationSerializer(read_only=True)
    integration_id = serializers.PrimaryKeyRelatedField(
        write_only=True, queryset=Integration.objects.all(), source="integration"
    )
    external_url = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    issue_id = serializers.SerializerMethodField()
    metadata = serializers.SerializerMethodField(required=False)

    class Meta:
        model = SessionRecordingExternalReference
        fields = [
            "id",
            "integration",
            "integration_id",
            "config",
            "session_recording_id",
            "external_url",
            "title",
            "issue_id",
            "metadata",
        ]
        read_only_fields = ["external_url", "title", "issue_id", "metadata"]

    def get_external_url(self, reference: SessionRecordingExternalReference) -> str:
        external_context = self._get_external_context(reference)

        if reference.integration.kind == Integration.IntegrationKind.LINEAR:
            url_key = LinearIntegration(reference.integration).url_key()
            return f"https://linear.app/{url_key}/issue/{external_context['id']}"
        elif reference.integration.kind == Integration.IntegrationKind.GITHUB:
            org = GitHubIntegration(reference.integration).organization()
            repository = external_context.get("repository", "")
            issue_number = external_context.get("id", "").lstrip("#")
            return f"https://github.com/{org}/{repository}/issues/{issue_number}"
        elif reference.integration.kind == Integration.IntegrationKind.GITLAB:
            gitlab = GitLabIntegration(reference.integration)
            issue_id = external_context.get("issue_id", "")
            return f"{gitlab.hostname}/{gitlab.project_path}/-/issues/{issue_id}" if issue_id else ""
        elif reference.integration.kind == Integration.IntegrationKind.JIRA:
            site_url = JiraIntegration(reference.integration).site_url()
            issue_key = external_context.get("id", "")
            return f"{site_url}/browse/{issue_key}"
        else:
            return ""

    def _get_external_context(self, reference: SessionRecordingExternalReference) -> dict[str, str]:
        return reference.external_context or {}

    def get_title(self, reference: SessionRecordingExternalReference) -> str:
        return self._get_external_context(reference).get("title", "")

    def get_issue_id(self, reference: SessionRecordingExternalReference) -> str:
        """Get the external issue ID (e.g., POST-123) from the issue tracker"""
        return self._get_external_context(reference).get("id", "")

    def get_metadata(self, reference: SessionRecordingExternalReference) -> dict[str, str]:
        """Get provider-specific metadata (e.g. repository for GitHub, project for Jira)"""
        external_context = self._get_external_context(reference)

        if reference.integration.kind == Integration.IntegrationKind.GITHUB:
            return {"repository": external_context.get("repository", "")}
        elif reference.integration.kind == Integration.IntegrationKind.JIRA:
            return {"project": external_context.get("project", "")}

        return {}

    def validate(self, data):
        """Ensure both session recording and integration belong to the same team"""
        team = self.context["get_team"]()
        integration = data["integration"]
        session_recording_id = data.get("session_recording_id")

        # recordings are created lazily
        session_recording, _ = SessionRecording.objects.get_or_create(
            session_id=session_recording_id,
            team=team,
        )

        data["session_recording"] = session_recording

        if integration.team_id != team.id:
            raise serializers.ValidationError("Integration does not belong to this team.")

        return data

    def _build_recording_url(self, team_id: int, session_id: str, config: dict[str, Any]) -> str:
        """Build session recording URL with optional timestamp"""
        recording_url = f"{settings.SITE_URL}/project/{team_id}/replay/{session_id}"

        if "timestamp" in config:
            timestamp_seconds = int(config.get("timestamp", 0))
            minutes = timestamp_seconds // 60
            seconds = timestamp_seconds % 60
            recording_url += f"?t={minutes}m{seconds}s"

        return recording_url

    def create(self, validated_data) -> SessionRecordingExternalReference:
        """
        Create external reference by calling provider-specific integration to create the issue.
        Auto-appends session recording URL (with timestamp) to the issue description.
        """
        team = self.context["get_team"]()
        session_recording: SessionRecording = validated_data.get("session_recording")
        integration: Integration = validated_data.get("integration")
        config: dict[str, Any] = validated_data.get("config")

        recording_url = self._build_recording_url(team.pk, session_recording.session_id, config)

        if integration.kind == Integration.IntegrationKind.LINEAR:
            title = config.get("title", "")
            config["description"] = f"{config.get('description', '')}\n\nPostHog recording: {recording_url}"
            external_context = LinearIntegration(integration).create_issue(
                team.pk, session_recording.session_id, config
            )
            external_context["title"] = title
        elif integration.kind == Integration.IntegrationKind.GITHUB:
            title = config.get("title", "")
            config["body"] = f"{config.get('body', '')}\n\n**PostHog recording:** {recording_url}"
            response = GitHubIntegration(integration).create_issue(config)
            external_context = {
                "id": f"#{response.get('number', '')}",
                "title": title,
                "repository": response.get("repository", ""),
            }
        elif integration.kind == Integration.IntegrationKind.GITLAB:
            title = config.get("title", "")
            config["body"] = f"{config.get('body', '')}\n\n**PostHog recording:** {recording_url}"
            response = GitLabIntegration(integration).create_issue(config)
            if not response.get("issue_id"):
                raise ValidationError("Failed to create GitLab issue")
            external_context = {
                "id": f"#{response.get('issue_id', '')}",
                "title": title,
                "issue_id": response.get("issue_id", ""),
            }
        elif integration.kind == Integration.IntegrationKind.JIRA:
            title = config.get("title", "")
            project_key = config.get("project_key", "")
            config["description"] = f"{config.get('description', '')}\n\nPostHog recording: {recording_url}"
            response = JiraIntegration(integration).create_issue(config)
            external_context = {
                "id": response.get("key", ""),
                "title": title,
                "project": project_key,
            }
        else:
            raise ValidationError(f"Integration kind '{integration.kind}' not supported")

        instance = SessionRecordingExternalReference.objects.create(
            session_recording=session_recording,
            integration=integration,
            external_context=external_context,
        )

        posthoganalytics.capture(
            distinct_id=str(team.pk),
            event="session_replay_external_issue_created",
            groups=groups(team.organization, team),
            properties={
                "session_recording_id": session_recording.session_id,
                "integration_kind": integration.kind,
            },
        )

        return instance


class SessionRecordingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    ViewSet for managing external references to session recordings.
    Supports creating issues in Linear, GitHub, and Gitlab from session replays.
    """

    scope_object = "INTERNAL"
    queryset = SessionRecordingExternalReference.objects.all()
    serializer_class = SessionRecordingExternalReferenceSerializer
