from __future__ import annotations

import json

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, Team

from ..models import AgentApplication, AgentSlackConnector


class TestAgentSlackConnectorAPI(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="slack-connector-agent",
            name="Slack connector agent",
            description="",
        )
        self.url = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/slack_connectors/"

    def test_repeated_registration_returns_the_same_connector(self) -> None:
        first = self.client.post(self.url, {"slack_workspace_id": "T01234567"}, format="json")
        second = self.client.post(self.url, {"slack_workspace_id": "T01234567"}, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.content)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.content)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(second.json()["public_routing_id"], first.json()["public_routing_id"])
        self.assertEqual(
            AgentSlackConnector.all_teams.filter(
                application=self.application,
                slack_workspace_id="T01234567",
            ).count(),
            1,
        )

    def test_retrieve_never_returns_encrypted_credentials(self) -> None:
        connector = AgentSlackConnector.all_teams.create(
            team_id=self.team.id,
            application=self.application,
            slack_workspace_id="T01234567",
            encrypted_credentials=json.dumps({"bot_token": "xoxb-secret", "signing_secret": "signing-secret"}),
        )

        response = self.client.get(f"{self.url}{connector.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertNotIn("encrypted_credentials", response.json())
        self.assertNotIn("xoxb-secret", response.content.decode())
        self.assertNotIn("signing-secret", response.content.decode())

    def test_application_from_another_team_cannot_register_a_connector(self) -> None:
        other_org = Organization.objects.create(name="other-org")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        foreign_application = AgentApplication.all_teams.create(
            team_id=other_team.id,
            slug="foreign-slack-connector-agent",
            name="Foreign Slack connector agent",
            description="",
        )
        url = f"/api/projects/{self.team.id}/agent_applications/{foreign_application.id}/slack_connectors/"

        response = self.client.post(url, {"slack_workspace_id": "T01234567"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)
        self.assertFalse(AgentSlackConnector.all_teams.filter(application=foreign_application).exists())
