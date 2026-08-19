"""Tests for the Linear integration."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import Integration, LinearIntegration


class TestLinearIntegrationModel(BaseTest):
    def create_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="linear",
            config={"data": {"viewer": {"organization": {"urlKey": "posthog"}}}},
            sensitive_config={"access_token": "ACCESS_TOKEN"},
        )

    def test_create_issue_passes_user_fields_as_graphql_variables(self):
        linear = LinearIntegration(self.create_integration())
        with patch.object(
            linear,
            "query",
            side_effect=[
                {"data": {"issueCreate": {"issue": {"identifier": "LIN-123"}}}},
                {"data": {"attachmentCreate": {"success": True}}},
            ],
        ) as mock_query:
            attachment_url = f'https://us.posthog.com/project/{self.team.id}/error_tracking/issue-id" }} mutation {{'
            result = linear.create_issue(
                attachment_url,
                {
                    "team_id": 'team-id" } mutation {',
                    "title": 'Title "quoted"',
                    "description": "Description",
                },
            )

        assert result == {"id": "LIN-123"}
        issue_query = mock_query.call_args_list[0].args[0]
        issue_variables = mock_query.call_args_list[0].kwargs["variables"]
        attachment_query = mock_query.call_args_list[1].args[0]
        attachment_variables = mock_query.call_args_list[1].kwargs["variables"]

        assert 'team-id" } mutation {' not in issue_query
        assert 'Title "quoted"' not in issue_query
        assert issue_variables == {
            "title": 'Title "quoted"',
            "description": "Description",
            "teamId": 'team-id" } mutation {',
        }
        assert 'issue-id" } mutation {' not in attachment_query
        assert attachment_variables["issueId"] == "LIN-123"
        assert attachment_variables["title"] == "PostHog issue"
        assert attachment_variables["url"].endswith(f'/project/{self.team.id}/error_tracking/issue-id" }} mutation {{')
