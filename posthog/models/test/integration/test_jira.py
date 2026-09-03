"""Tests for the Jira integration."""

import pytest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError

from posthog.models.integration import Integration, JiraIntegration


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
