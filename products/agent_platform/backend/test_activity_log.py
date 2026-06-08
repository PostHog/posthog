"""
Activity-log integration tests for agent_platform.

Verifies that AgentApplication + AgentRevision saves land in the central
ActivityLog table via the standard ModelActivityMixin + receiver path,
that field exclusions silence noise, and that `encrypted_env` is masked.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from .models import AgentApplication, AgentRevision


class TestAgentApplicationActivityLog(APIBaseTest):
    def test_create_logs_a_created_entry(self) -> None:
        ActivityLog.objects.filter(scope="AgentApplication").delete()
        app = AgentApplication.objects.create(
            team=self.team,
            slug="auditable-agent",
            name="Auditable",
            description="",
        )
        entries = list(ActivityLog.objects.filter(scope="AgentApplication", item_id=str(app.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        assert entry.activity == "created"
        assert entry.team_id == self.team.id
        assert entry.detail["name"] == "auditable-agent"

    def test_rename_logs_an_updated_entry_with_field_diff(self) -> None:
        app = AgentApplication.objects.create(
            team=self.team,
            slug="agent-a",
            name="Agent A",
            description="",
        )
        ActivityLog.objects.filter(scope="AgentApplication").delete()

        app.name = "Agent A (renamed)"
        app.save()

        entries = list(ActivityLog.objects.filter(scope="AgentApplication", item_id=str(app.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        assert entry.activity == "updated"
        changed_fields = [c["field"] for c in entry.detail["changes"]]
        assert "name" in changed_fields

    def test_archive_logs_an_updated_entry_diffing_the_archived_flag(self) -> None:
        app = AgentApplication.objects.create(
            team=self.team,
            slug="ephemeral",
            name="Ephemeral",
            description="",
        )
        ActivityLog.objects.filter(scope="AgentApplication").delete()

        app.archived = True
        app.save()

        entries = list(ActivityLog.objects.filter(scope="AgentApplication", item_id=str(app.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        assert entry.activity == "updated"
        changed_fields = [c["field"] for c in entry.detail["changes"]]
        # The archived flip surfaces — archived_at is in field_exclusions so
        # it doesn't pollute the diff.
        assert "archived" in changed_fields
        assert "archived_at" not in changed_fields

    def test_encrypted_env_change_is_masked_not_leaked(self) -> None:
        app = AgentApplication.objects.create(
            team=self.team,
            slug="secret-agent",
            name="Secret",
            description="",
        )
        ActivityLog.objects.filter(scope="AgentApplication").delete()

        app.encrypted_env = '{"ACME_KEY": "rotated-value"}'
        app.save()

        entries = list(ActivityLog.objects.filter(scope="AgentApplication", item_id=str(app.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        changes = entry.detail["changes"]
        env_changes = [c for c in changes if c["field"] == "encrypted_env"]
        assert len(env_changes) == 1
        # The mask substitutes a marker for both before and after; the actual
        # secret value never reaches the log payload.
        assert "rotated-value" not in str(env_changes[0])


class TestAgentRevisionActivityLog(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.objects.create(
            team=self.team,
            slug="rev-host",
            name="Rev Host",
            description="",
        )

    def test_create_logs_a_created_entry(self) -> None:
        ActivityLog.objects.filter(scope="AgentRevision").delete()
        rev = AgentRevision.objects.create(
            application=self.application,
            bundle_uri="s3://test/",
            spec={},
        )
        entries = list(ActivityLog.objects.filter(scope="AgentRevision", item_id=str(rev.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        assert entry.activity == "created"
        # Display name format from activity.py.
        assert entry.detail["name"].startswith("rev-host@")
        assert entry.detail["name"].endswith(" (draft)")

    def test_state_transition_logs_an_updated_entry(self) -> None:
        rev = AgentRevision.objects.create(
            application=self.application,
            bundle_uri="s3://test/",
            spec={},
        )
        ActivityLog.objects.filter(scope="AgentRevision").delete()

        rev.state = "ready"
        rev.bundle_sha256 = "a" * 64
        rev.save()

        entries = list(ActivityLog.objects.filter(scope="AgentRevision", item_id=str(rev.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        assert entry.activity == "updated"
        changed_fields = {c["field"] for c in entry.detail["changes"]}
        assert "state" in changed_fields
        assert "bundle_sha256" in changed_fields
        # `bundle_uri` is in field_exclusions; it shouldn't surface.
        assert "bundle_uri" not in changed_fields

    def test_spec_edit_logs_an_updated_entry(self) -> None:
        rev = AgentRevision.objects.create(
            application=self.application,
            bundle_uri="s3://test/",
            spec={"model": "claude-opus-4-7"},
        )
        ActivityLog.objects.filter(scope="AgentRevision").delete()

        rev.spec = {"model": "claude-opus-4-7", "entrypoint": "agent.md"}
        rev.save()

        entries = list(ActivityLog.objects.filter(scope="AgentRevision", item_id=str(rev.id)))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.detail is not None
        changed_fields = {c["field"] for c in entry.detail["changes"]}
        assert "spec" in changed_fields
