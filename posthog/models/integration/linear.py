"""Linear integration."""

from typing import Any

import requests
import structlog
from rest_framework.exceptions import ValidationError

from . import common, model

logger = structlog.get_logger(__name__)


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
        # Linear reports failures in a 200 body; without this check a failed create would
        # persist a reference with id None. Nothing was created, so raising is safe.
        if body.get("errors") or not linear_issue_id:
            raise ValidationError("Failed to create the Linear issue")

        # Best-effort: the Linear issue already exists at this point, so failing the whole
        # create over a missing back-link would produce duplicate issues on retry.
        try:
            self.create_attachment(linear_issue_id, attachment_url)
        except ValidationError:
            logger.warning("linear_issue_attachment_failed", issue_id=linear_issue_id)

        return {"id": linear_issue_id}

    def create_attachment(self, issue_id: str, url: str) -> None:
        """Attach a PostHog issue link to a Linear issue (shows as a back-link in Linear).

        Raises on failure: Linear reports errors in the GraphQL body with HTTP 200,
        and the mutation itself can report success=false.
        """
        link_attachment_query = """
        mutation AttachmentCreate($issueId: String!, $title: String!, $url: String!) {
            attachmentCreate(input: { issueId: $issueId, title: $title, url: $url }) {
                success
            }
        }
        """
        body = self.query(
            link_attachment_query,
            variables={"issueId": issue_id, "title": "PostHog issue", "url": url},
        )
        if body.get("errors") or not common.dot_get(body, "data.attachmentCreate.success"):
            raise ValidationError("Failed to attach the PostHog link to the Linear issue")

    def search_issues(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Search existing Linear issues by title / identifier for the link-existing flow.

        A blank query lists recently updated issues instead - searchIssues requires a term.
        """
        if query.strip():
            search_query = """
            query SearchIssues($term: String!, $first: Int!) {
                searchIssues(term: $term, first: $first) {
                    nodes { identifier title url }
                }
            }
            """
            body = self.query(search_query, variables={"term": query, "first": limit})
            nodes_path = "data.searchIssues"
        else:
            recent_query = """
            query RecentIssues($first: Int!) {
                issues(first: $first, orderBy: updatedAt) {
                    nodes { identifier title url }
                }
            }
            """
            body = self.query(recent_query, variables={"first": limit})
            nodes_path = "data.issues"
        if body.get("errors") or common.dot_get(body, nodes_path) is None:
            raise ValidationError("Failed to search Linear issues")
        nodes = common.dot_get(body, f"{nodes_path}.nodes") or []
        results: list[dict[str, Any]] = []
        for node in nodes:
            identifier = node.get("identifier")
            if not identifier:
                continue
            results.append(
                {
                    "id": identifier,
                    "title": node.get("title") or identifier,
                    "url": node.get("url") or "",
                    # Matches the shape LinearIntegration.create_issue stores.
                    "external_context": {"id": identifier},
                }
            )
        return results

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
            json={"query": query, "variables": variables or {}},
            timeout=10,
        )
        return response.json()
