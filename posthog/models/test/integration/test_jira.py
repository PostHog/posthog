"""Tests for the Jira integration."""

import pytest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import ValidationError

from posthog.models.integration import Integration, JiraIntegration
from posthog.models.integration.common import ERROR_TOKEN_REFRESH_FAILED


def jira_response(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock(status_code=status_code)
    response.json.return_value = body or {}
    return response


class TestJiraIntegrationModel:
    @staticmethod
    def integration() -> MagicMock:
        return MagicMock(
            id=123,
            team_id=456,
            kind=Integration.IntegrationKind.JIRA,
            config={"cloud_id": "cloud-id"},
            sensitive_config={"access_token": "access-token", "refresh_token": "refresh-token"},
            errors="",
        )

    @patch("posthog.models.integration.jira.capture_exception")
    @patch("posthog.models.integration.jira.requests.request")
    def test_create_issue_captures_structured_error_details(self, mock_request, mock_capture_exception):
        mock_request.return_value.status_code = 400
        mock_request.return_value.headers = {"Content-Type": "application/json"}
        mock_request.return_value.json.return_value = {
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
    @patch("posthog.models.integration.jira.requests.request")
    def test_create_issue_captures_non_json_response_metadata(self, mock_request, mock_capture_exception):
        mock_request.return_value.status_code = 502
        mock_request.return_value.headers = {"Content-Type": "text/html"}
        mock_request.return_value.json.side_effect = ValueError

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

    @patch.object(JiraIntegration, "refresh_access_token")
    @patch("posthog.models.integration.jira.requests.request")
    def test_search_issues_retries_once_with_a_refreshed_token(self, mock_request, mock_refresh):
        mock_request.side_effect = [
            jira_response(401),
            jira_response(
                200, {"sections": [{"issues": [{"id": "10001", "key": "ENG-1", "summaryText": "Checkout"}]}]}
            ),
        ]
        integration = self.integration()

        results = JiraIntegration(integration).search_issues("checkout")

        assert mock_refresh.call_count == 1
        assert [result["external_context"]["key"] for result in results] == ["ENG-1"]
        assert integration.errors == ""

    @pytest.mark.parametrize(
        "call_jira",
        [
            lambda jira: jira.search_issues("checkout"),
            lambda jira: jira.list_projects(),
            lambda jira: jira.create_issue({"project_key": "ENG", "title": "Title", "description": "Details"}),
        ],
        ids=["search_issues", "list_projects", "create_issue"],
    )
    @patch.object(JiraIntegration, "refresh_access_token")
    @patch("posthog.models.integration.jira.requests.request")
    def test_prompts_a_reconnect_when_the_token_stays_invalid(self, mock_request, mock_refresh, call_jira):
        mock_request.return_value = jira_response(401)
        integration = self.integration()

        with pytest.raises(ValidationError) as error:
            call_jira(JiraIntegration(integration))

        assert error.value.args[0] == (
            "This integration's authentication is no longer valid. "
            "Please reconnect or disconnect this integration and connect a different account."
        )
        assert integration.errors == ERROR_TOKEN_REFRESH_FAILED
        integration.save.assert_called_once_with(update_fields=["errors"])

    @patch("posthog.models.integration.jira.requests.request")
    def test_search_issues_explains_a_permission_error(self, mock_request):
        mock_request.return_value = jira_response(403)

        with pytest.raises(ValidationError) as error:
            JiraIntegration(self.integration()).search_issues("checkout")

        assert error.value.args[0] == (
            "This integration does not have permission to access this resource. "
            "Please check the account permissions on the provider side."
        )
