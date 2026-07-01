from __future__ import annotations

from typing import Any

from posthog.test.base import APIBaseTest

from rest_framework import serializers

from parameterized import parameterized

from posthog.models import User

from products.mcp_store.backend.models import MCPServerInstallation

from ..models import AgentApplication, AgentRevision
from ..presentation.serializers import AgentRevisionSerializer


def _spec_with_connection(connection_id: str) -> dict[str, Any]:
    return {
        "mcps": [
            {
                "id": "m",
                "url": "https://mcp.example.test/mcp",
                "kind": "agent",
                "default_tool_approval": "approve",
                "connection": connection_id,
            }
        ]
    }


class TestMcpConnectionAuthz(APIBaseTest):
    databases = {"default", "agent_platform_db_writer", "agent_platform_db_reader"}

    def setUp(self) -> None:
        super().setUp()
        self.other = User.objects.create_and_join(self.organization, "teammate@posthog.com", "pw")
        self.mine = MCPServerInstallation.objects.create(
            team=self.team, user=self.user, url="https://mine.example.test/mcp"
        )
        self.theirs = MCPServerInstallation.objects.create(
            team=self.team, user=self.other, url="https://theirs.example.test/mcp"
        )
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id, slug="agent", name="Agent", description=""
        )

    def _serializer(self, user: User | None, instance: AgentRevision | None = None) -> AgentRevisionSerializer:
        request = type("Req", (), {"user": user})()
        return AgentRevisionSerializer(instance=instance, context={"request": request, "get_team": lambda: self.team})

    def test_accepts_connection_owned_by_author(self) -> None:
        spec = _spec_with_connection(str(self.mine.id))
        self.assertEqual(self._serializer(self.user).validate_spec(spec)["mcps"][0]["connection"], str(self.mine.id))

    def test_accepts_spec_without_any_connection(self) -> None:
        spec = {"mcps": [{"id": "m", "url": "https://x.test", "kind": "principal", "auth": {"provider": "gh"}}]}
        self.assertEqual(self._serializer(self.user).validate_spec(spec), spec | {"skills": []})

    @parameterized.expand(
        [
            ("teammate_owned_idor",),
            ("nonexistent_uuid",),
            ("not_a_uuid",),
        ]
    )
    def test_rejects_unowned_connection(self, case: str) -> None:
        connection_id = {
            "teammate_owned_idor": lambda: str(self.theirs.id),
            "nonexistent_uuid": lambda: "00000000-0000-0000-0000-000000000000",
            "not_a_uuid": lambda: "not-a-uuid",
        }[case]()
        with self.assertRaises(serializers.ValidationError):
            self._serializer(self.user).validate_spec(_spec_with_connection(connection_id))

    def test_editor_can_save_owners_revision_referencing_owners_connection(self) -> None:
        revision = AgentRevision.all_teams.create(
            application=self.application, state="draft", spec={}, created_by_id=self.user.id
        )
        result = self._serializer(self.other, instance=revision).validate_spec(_spec_with_connection(str(self.mine.id)))
        self.assertEqual(result["mcps"][0]["connection"], str(self.mine.id))

    def test_editor_cannot_add_their_own_connection_to_owners_revision(self) -> None:
        revision = AgentRevision.all_teams.create(
            application=self.application, state="draft", spec={}, created_by_id=self.user.id
        )
        with self.assertRaises(serializers.ValidationError):
            self._serializer(self.other, instance=revision).validate_spec(_spec_with_connection(str(self.theirs.id)))
