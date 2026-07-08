"""
Object-level access control on the agent memory / table endpoints.

`AgentMemoryViewSet` is a plain `ViewSet`, so it resolves the application via
its own `_get_application()` rather than the mixin's `get_object()`. That
helper must still run `check_object_permissions`, or a user with team access
but no access to a specific application could read its memory files / tables
by guessing the slug or UUID. These tests pin the team-scoping boundary and
that the authorized path is not over-blocked by the added check.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from ..models import AgentApplication


class TestMemoryViewSetAuthz(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id, slug="memo-agent", name="Memo agent", description=""
        )
        self.tables_url = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/memory/tables/"

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_authorized_member_can_list_tables(self, mock_janitor: MagicMock) -> None:
        # The added object-permission check must not over-block or crash the
        # normal path: a team member resolves the app and proxies to the janitor.
        mock_janitor.return_value.list_tables.return_value = {"tables": []}
        res = self.client.get(self.tables_url)
        self.assertEqual(res.status_code, 200, res.content)
        mock_janitor.return_value.list_tables.assert_called_once()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_application_from_another_team_is_not_readable(self, mock_janitor: MagicMock) -> None:
        # An application owned by a different team must not be reachable through
        # this team's URL — resolution is team-scoped, so the janitor is never
        # called and no rows leak across the tenant boundary.
        other_org = Organization.objects.create(name="other-org")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        foreign = AgentApplication.all_teams.create(
            team_id=other_team.id, slug="foreign", name="Foreign", description=""
        )
        url = f"/api/projects/{self.team.id}/agent_applications/{foreign.id}/memory/tables/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404, res.content)
        mock_janitor.return_value.list_tables.assert_not_called()
