"""Tests for the Microsoft Teams integration."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models.integration import Integration, MicrosoftTeamsIntegration


def graph_response(body: dict) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = body
    return response


class TestMicrosoftTeamsIntegration(SimpleTestCase):
    @patch("posthog.models.integration.microsoft_teams.requests.get")
    def test_list_channels_follows_graph_pages_but_not_other_hosts(self, mock_get):
        mock_get.side_effect = [
            graph_response(
                {
                    "value": [{"id": "19:a@thread.tacv2", "displayName": "General", "membershipType": "standard"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/teams/t/channels?$skiptoken=2",
                }
            ),
            graph_response(
                {
                    "value": [{"id": "19:b@thread.tacv2", "displayName": "Support", "membershipType": "shared"}],
                    "@odata.nextLink": "https://attacker.example.com/steal",
                }
            ),
        ]
        integration = Integration(kind="microsoft-teams", sensitive_config={"access_token": "token"})

        channels = MicrosoftTeamsIntegration(integration).list_channels("t")

        assert channels == [
            {"id": "19:a@thread.tacv2", "name": "General", "membership_type": "standard"},
            {"id": "19:b@thread.tacv2", "name": "Support", "membership_type": "shared"},
        ]
        assert [call.args[0] for call in mock_get.call_args_list] == [
            "https://graph.microsoft.com/v1.0/teams/t/channels",
            "https://graph.microsoft.com/v1.0/teams/t/channels?$skiptoken=2",
        ]
