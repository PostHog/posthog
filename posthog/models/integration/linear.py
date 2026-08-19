"""Linear integration."""

from typing import Any

import requests

from . import common, model


class LinearIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "linear":
            raise Exception("LinearIntegration init called with Integration with wrong 'kind'")

        self.integration = integration

    def url_key(self) -> str:
        return common.dot_get(self.integration.config, "data.viewer.organization.urlKey")

    def list_teams(self) -> list[dict]:
        body = self.query(f"{{ teams {{ nodes {{ id name }} }} }}")
        teams = common.dot_get(body, "data.teams.nodes")
        return teams

    def create_issue(self, attachment_url: str, config: dict[str, str]) -> dict[str, str]:
        title: str = config.pop("title")
        description: str = config.pop("description")
        linear_team_id = config.pop("team_id")

        issue_create_query = """
        mutation IssueCreate($title: String!, $description: String!, $teamId: String!) {
            issueCreate(input: { title: $title, description: $description, teamId: $teamId }) {
                success
                issue { identifier }
            }
        }
        """
        body = self.query(
            issue_create_query,
            variables={"title": title, "description": description, "teamId": linear_team_id},
        )
        linear_issue_id = common.dot_get(body, "data.issueCreate.issue.identifier")

        link_attachment_query = """
        mutation AttachmentCreate($issueId: String!, $title: String!, $url: String!) {
            attachmentCreate(input: { issueId: $issueId, title: $title, url: $url }) {
                success
            }
        }
        """
        self.query(
            link_attachment_query,
            variables={"issueId": linear_issue_id, "title": "PostHog issue", "url": attachment_url},
        )

        return {"id": linear_issue_id}

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
            json={"query": query, "variables": variables or {}},
            timeout=10,
        )
        return response.json()
