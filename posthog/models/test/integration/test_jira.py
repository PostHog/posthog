"""Tests for the Jira integration."""

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.integration import Assignee, Integration, JiraIntegration, ReconnectRequired


class TestJiraIntegrationModel:
    @staticmethod
    def integration() -> MagicMock:
        return MagicMock(
            id=123,
            team_id=456,
            kind=Integration.IntegrationKind.JIRA,
            config={"cloud_id": "cloud-id"},
            sensitive_config={"access_token": "access-token"},
        )

    @patch("posthog.models.integration.jira.capture_exception")
    @patch("posthog.models.integration.jira.requests.post")
    def test_create_issue_captures_structured_error_details(self, mock_post, mock_capture_exception):
        mock_post.return_value.status_code = 400
        mock_post.return_value.headers = {"Content-Type": "application/json"}
        mock_post.return_value.json.return_value = {
            "errorMessages": ["Issue type is not available"],
            "errors": {"summary": "Summary is required"},
        }

        with pytest.raises(ValidationError) as error:
            JiraIntegration(self.integration()).create_issue(
                {"project_key": "ENG", "title": "Checkout failed", "description": "Details"}
            )

        assert error.value.args[0] == (
            "Could not create the Jira issue. Check the project's issue settings and try again."
        )
        captured_error = mock_capture_exception.call_args.args[0]
        assert str(captured_error) == "Jira issue creation failed"
        assert mock_capture_exception.call_args.kwargs["additional_properties"] == {
            "jira_status_code": 400,
            "jira_response_content_type": "application/json",
            "integration_id": 123,
            "team_id": 456,
            "jira_error_messages": ["Issue type is not available"],
            "jira_field_errors": {"summary": "Summary is required"},
            "jira_response_keys": ["errorMessages", "errors"],
        }

    @patch("posthog.models.integration.jira.capture_exception")
    @patch("posthog.models.integration.jira.requests.post")
    def test_create_issue_captures_non_json_response_metadata(self, mock_post, mock_capture_exception):
        mock_post.return_value.status_code = 502
        mock_post.return_value.headers = {"Content-Type": "text/html"}
        mock_post.return_value.json.side_effect = ValueError

        with pytest.raises(ValidationError) as error:
            JiraIntegration(self.integration()).create_issue(
                {"project_key": "ENG", "title": "Checkout failed", "description": "Details"}
            )

        assert error.value.args[0] == (
            "Could not create the Jira issue. Check the project's issue settings and try again."
        )
        assert mock_capture_exception.call_args.kwargs["additional_properties"] == {
            "jira_status_code": 502,
            "jira_response_content_type": "text/html",
            "integration_id": 123,
            "team_id": 456,
        }

    @parameterized.expand(
        [
            (
                "plain_text_stays_one_paragraph",
                "Details\nPostHog issue: https://example.com/issue/1",
                [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Details\nPostHog issue: https://example.com/issue/1"}],
                    }
                ],
            ),
            (
                "fence_becomes_code_block",
                'Checkout failed\n\n```\nTypeError: boom\n  File "app.js", line: 3\n```\n\nPostHog issue: https://example.com/issue/1',
                [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Checkout failed"}]},
                    {
                        "type": "codeBlock",
                        "content": [{"type": "text", "text": 'TypeError: boom\n  File "app.js", line: 3'}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "PostHog issue: https://example.com/issue/1"}],
                    },
                ],
            ),
            (
                "longer_closing_fence_closes_block",
                "```\nboom\n````\nafter",
                [
                    {"type": "codeBlock", "content": [{"type": "text", "text": "boom"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
                ],
            ),
            (
                "unclosed_fence_runs_to_end",
                "Details\n```js\nboom\n\nPostHog issue: https://example.com/issue/1",
                [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Details"}]},
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "js"},
                        "content": [{"type": "text", "text": "boom\n\nPostHog issue: https://example.com/issue/1"}],
                    },
                ],
            ),
            (
                "shorter_inner_fence_stays_in_code",
                "````python\nprint('x')\n```\n````",
                [
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "python"},
                        "content": [{"type": "text", "text": "print('x')\n```"}],
                    }
                ],
            ),
        ]
    )
    @patch("posthog.models.integration.jira.requests.post")
    def test_create_issue_converts_description_to_adf(self, _name, description, expected_content, mock_post):
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"key": "ENG-1", "id": "10001"}

        JiraIntegration(self.integration()).create_issue(
            {"project_key": "ENG", "title": "Checkout failed", "description": description}
        )

        assert mock_post.call_args.kwargs["json"]["fields"]["description"] == {
            "type": "doc",
            "version": 1,
            "content": expected_content,
        }

    @parameterized.expand(
        [
            ("with_assignee", {"assignee": "account-id"}, {"accountId": "account-id"}),
            ("without_assignee", {}, None),
        ]
    )
    @patch("posthog.models.integration.jira.requests.post")
    def test_create_issue_sets_assignee_by_account_id(self, _name, extra_config, expected_assignee, mock_post):
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"key": "ENG-1", "id": "10001"}

        JiraIntegration(self.integration()).create_issue(
            {"project_key": "ENG", "title": "Checkout failed", "description": "Details", **extra_config}
        )

        assert mock_post.call_args.kwargs["json"]["fields"].get("assignee") == expected_assignee

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @patch("posthog.models.integration.jira.requests.get")
    def test_list_assignees_requires_reconnect(self, _name, status_code, mock_get):
        integration = self.integration()
        integration.config = {"cloud_id": "cloud-id", "refreshed_at": 9999999999}
        mock_get.return_value.status_code = status_code

        with pytest.raises(ReconnectRequired):
            JiraIntegration(integration).list_assignees("ENG")

    @patch("posthog.models.integration.jira.requests.get")
    def test_list_assignees_searches_and_skips_inactive_users(self, mock_get):
        integration = self.integration()
        integration.config = {"cloud_id": "cloud-id", "scope": "read:jira-work read:jira-user"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            {"accountId": "a1", "displayName": "Ada", "active": True},
            {"accountId": "a2", "displayName": "Gone", "active": False},
        ]

        assert JiraIntegration(integration).list_assignees("ENG", " ad ") == [Assignee(id="a1", name="Ada")]
        assert mock_get.call_args.kwargs["params"] == {"project": "ENG", "maxResults": "100", "query": "ad"}
