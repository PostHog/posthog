"""Jira integration."""

import time
from datetime import timedelta
from typing import Any, NoReturn

import requests
import structlog
from rest_framework.exceptions import ValidationError

from posthog.exceptions_capture import capture_exception

from . import common, model, oauth

logger = structlog.get_logger(__name__)


class JiraIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "jira":
            raise Exception("JiraIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def cloud_id(self) -> str | None:
        """Get the Atlassian cloud ID from the integration config"""
        return common.dot_get(self.integration.config, "cloud_id")

    def site_name(self) -> str | None:
        """Get the Jira site name from the integration config"""
        return common.dot_get(self.integration.config, "site_name")

    def site_url(self) -> str:
        """Get the Jira site URL from the integration config"""
        return common.dot_get(self.integration.config, "site_url", "")

    def access_token_expired(self, time_threshold: timedelta | None = None) -> bool:
        """Check if the Atlassian access token has expired or is close to expiring"""
        refresh_token = self.integration.sensitive_config.get("refresh_token")
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")

        if not refresh_token:
            return False

        if not expires_in or not refreshed_at:
            return False

        # To be safe we refresh if it's halfway through the expiry
        time_threshold = time_threshold or timedelta(seconds=expires_in / 2)

        return time.time() > refreshed_at + expires_in - time_threshold.total_seconds()

    def refresh_access_token(self) -> None:
        """Refresh the Atlassian access token using the refresh token"""
        oauth_integration = oauth.OauthIntegration(self.integration)
        oauth_integration.refresh_access_token()

    def _ensure_token_valid(self) -> None:
        """Proactively refresh token if it's close to expiring to avoid intermittent 401s"""
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("JiraIntegration: token refresh pre-check failed", exc_info=True)

    def _raise_create_issue_error(self, response: requests.Response, response_body: Any) -> NoReturn:
        properties: dict[str, Any] = {
            "jira_status_code": response.status_code,
            "jira_response_content_type": response.headers.get("Content-Type"),
            "integration_id": self.integration.id,
            "team_id": self.integration.team_id,
        }
        if isinstance(response_body, dict):
            properties.update(
                {
                    "jira_error_messages": response_body.get("errorMessages"),
                    "jira_field_errors": response_body.get("errors"),
                    "jira_response_keys": list(response_body.keys()),
                }
            )

        capture_exception(Exception("Jira issue creation failed"), additional_properties=properties)
        raise ValidationError("Could not create the Jira issue. Check the project's issue settings and try again.")

    def list_projects(self) -> list[dict]:
        """List all Jira projects accessible to the user"""
        cloud_id = self.cloud_id()
        if not cloud_id:
            raise ValidationError("Jira integration missing cloud_id - the integration may not be properly configured")

        self._ensure_token_valid()

        response = requests.get(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search",
            headers={
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "Accept": "application/json",
            },
            timeout=10,
        )
        body = response.json()
        projects = body.get("values", [])
        return [{"id": p["id"], "key": p["key"], "name": p["name"]} for p in projects]

    def create_issue(self, config: dict[str, str]) -> dict[str, str]:
        """Create a Jira issue and return the issue key"""
        cloud_id = self.cloud_id()
        if not cloud_id:
            raise ValidationError("Jira integration missing cloud_id - the integration may not be properly configured")

        self._ensure_token_valid()

        title = config.get("title")
        description = config.get("description")
        project_key = config.get("project_key")

        # Jira uses Atlassian Document Format (ADF) for description
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": title,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                },
                "issuetype": {"name": "Task"},
            }
        }

        response = requests.post(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue",
            headers={
                "Authorization": f"Bearer {self.integration.sensitive_config['access_token']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )

        try:
            issue = response.json()
        except ValueError:
            issue = None

        if response.status_code != 201:
            self._raise_create_issue_error(response, issue)

        if not isinstance(issue, dict) or not issue.get("key"):
            self._raise_create_issue_error(response, issue)

        return {"key": issue["key"], "id": issue.get("id", "")}
