"""Tests for the Linear integration."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.integration import Integration, LinearIntegration


class TestLinearIntegrationModel(BaseTest):
    def create_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="linear",
            config={"data": {"viewer": {"organization": {"urlKey": "posthog"}}}},
            sensitive_config={"access_token": "ACCESS_TOKEN"},
        )

    def test_search_issues_raises_on_graphql_errors(self):
        # An expired token or GraphQL error must not be reported as a valid empty result.
        linear = LinearIntegration(self.create_integration())
        with patch.object(linear, "query", return_value={"errors": [{"message": "unauthorized"}]}):
            with self.assertRaises(ValidationError):
                linear.search_issues("boom")

    def test_search_issues_lists_recent_issues_for_blank_query(self):
        # searchIssues requires a term, so a blank picker query must use the plain issues
        # listing instead of silently returning nothing.
        linear = LinearIntegration(self.create_integration())
        body = {"data": {"issues": {"nodes": [{"identifier": "ENG-7", "title": "Recent", "url": "https://l/7"}]}}}
        with patch.object(linear, "query", return_value=body) as mock_query:
            results = linear.search_issues("   ")
        assert [result["id"] for result in results] == ["ENG-7"]
        assert "searchIssues" not in mock_query.call_args.args[0]

    @parameterized.expand(
        [
            ("top_level_errors", {"errors": [{"message": "forbidden"}]}),
            ("mutation_failure", {"data": {"attachmentCreate": {"success": False}}}),
        ]
    )
    def test_create_attachment_raises_on_failure(self, _name, response_body):
        # Linear reports failures in a 200 body; treating them as success would let callers
        # persist references whose promised back-link was never created.
        linear = LinearIntegration(self.create_integration())
        with patch.object(linear, "query", return_value=response_body):
            with self.assertRaises(ValidationError):
                linear.create_attachment("LIN-123", "https://us.posthog.com/error_tracking/issue-id")

    def test_create_issue_raises_when_issue_creation_fails(self):
        # A failed issueCreate must not fall through to an attachment attempt and a
        # persisted {"id": None} reference.
        linear = LinearIntegration(self.create_integration())
        with patch.object(linear, "query", return_value={"errors": [{"message": "forbidden"}]}) as mock_query:
            with self.assertRaises(ValidationError):
                linear.create_issue(
                    "https://us.posthog.com/error_tracking/issue-id",
                    {"team_id": "team-id", "title": "Title", "description": "Description"},
                )
        assert mock_query.call_count == 1

    def test_create_issue_succeeds_when_attachment_fails(self):
        # The Linear issue already exists when the attachment fires, so a failed back-link
        # must not fail the create (retrying would duplicate the issue).
        linear = LinearIntegration(self.create_integration())
        with patch.object(
            linear,
            "query",
            side_effect=[
                {"data": {"issueCreate": {"issue": {"identifier": "LIN-123"}}}},
                {"errors": [{"message": "rate limited"}]},
            ],
        ):
            result = linear.create_issue(
                "https://us.posthog.com/error_tracking/issue-id",
                {"team_id": "team-id", "title": "Title", "description": "Description"},
            )

        assert result == {"id": "LIN-123"}

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
