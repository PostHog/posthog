"""Linear integration."""

import re
import math
import time
from collections.abc import Sequence
from typing import Any

import requests
import structlog
from rest_framework.exceptions import ValidationError

from posthog.integrations.contracts import IntegrationRecord

from . import common, model
from .assignees import MAX_ASSIGNEES, Assignee, AssigneeLookupFailed

logger = structlog.get_logger(__name__)

_ISSUE_IDENTIFIER = re.compile(r"([A-Za-z0-9]+)-([0-9]+)")

# Linear counts requests over a one-hour window, so its reset time is never further away than that.
_RATE_LIMIT_WINDOW_SECONDS = 3600
_RATE_LIMIT_DEFAULT_WAIT_SECONDS = 60


class LinearIntegrationError(Exception):
    """A Linear read that failed, so the caller retries instead of acting on a guessed answer."""


class LinearRateLimitedError(LinearIntegrationError):
    """Linear refused a read because the token spent its hourly budget. Retry after `retry_after_seconds`."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Linear rate limit exceeded, retry in {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


def _rate_limit_wait_seconds(response: requests.Response) -> int:
    reset_ms = response.headers.get("X-RateLimit-Requests-Reset")
    try:
        wait = math.ceil(int(reset_ms) / 1000 - time.time()) if reset_ms else _RATE_LIMIT_DEFAULT_WAIT_SECONDS
    except ValueError:
        wait = _RATE_LIMIT_DEFAULT_WAIT_SECONDS
    return min(max(wait, 1), _RATE_LIMIT_WINDOW_SECONDS)


class LinearIntegration:
    integration: model.Integration

    def __init__(self, integration: IntegrationRecord) -> None:
        if integration.kind != "linear":
            raise Exception("LinearIntegration init called with Integration with wrong 'kind'")

        self.integration = model.integration_model(integration)

    def url_key(self) -> str:
        return common.dot_get(self.integration.config, "data.viewer.organization.urlKey")

    def list_teams(self) -> list[dict]:
        body = self.query(f"{{ teams {{ nodes {{ id name }} }} }}")
        teams = common.dot_get(body, "data.teams.nodes")
        return teams

    def list_assignees(self, team_id: str, search: str = "") -> list[Assignee]:
        """Active members of the team, filtered by name when ``search`` is set."""
        search = search.strip()
        user_filter = (
            {"or": [{"name": {"containsIgnoreCase": search}}, {"displayName": {"containsIgnoreCase": search}}]}
            if search
            else None
        )
        body = self.query(
            """
            query TeamMembers($teamId: String!, $first: Int!, $filter: UserFilter) {
                team(id: $teamId) { members(first: $first, filter: $filter) { nodes { id name displayName active } } }
            }
            """,
            variables={"teamId": team_id, "first": MAX_ASSIGNEES, "filter": user_filter},
        )
        if body.get("errors"):
            raise AssigneeLookupFailed("Failed to list the Linear team members")
        members = common.dot_get(body, "data.team.members.nodes") or []
        return [
            Assignee(id=member["id"], name=member.get("displayName") or member["name"])
            for member in members
            if member.get("active", True)
        ]

    def create_issue(self, attachment_url: str, config: dict[str, str]) -> dict[str, str]:
        title: str = config.pop("title")
        description: str = config.pop("description")
        linear_team_id = config.pop("team_id")
        assignee_id = config.pop("assignee", None)

        issue_create_query = """
        mutation IssueCreate($title: String!, $description: String!, $teamId: String!, $assigneeId: String) {
            issueCreate(input: { title: $title, description: $description, teamId: $teamId, assigneeId: $assigneeId }) {
                success
                issue { identifier }
            }
        }
        """
        body = self.query(
            issue_create_query,
            variables={
                "title": title,
                "description": description,
                "teamId": linear_team_id,
                "assigneeId": assignee_id or None,
            },
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

    def close_issue(self, issue_id: str, *, completed: bool = False) -> None:
        """Move an issue to its team's completed or canceled state. Raises on failure.

        Linear has no generic "close" verb: an issue closes by moving to a workflow state, and
        the state ids differ per team. So read the issue's own team states first.
        """
        state_type = "completed" if completed else "canceled"
        states_query = """
        query IssueCloseState($id: String!, $stateType: String!) {
            issue(id: $id) {
                team { states(filter: { type: { eq: $stateType } }) { nodes { id } } }
            }
        }
        """
        body = self.query(states_query, variables={"id": issue_id, "stateType": state_type})
        nodes = common.dot_get(body, "data.issue.team.states.nodes") or []
        if body.get("errors") or not nodes:
            raise ValidationError(f"Failed to find a {state_type} state for the Linear issue")

        update_query = """
        mutation IssueClose($id: String!, $stateId: String!) {
            issueUpdate(id: $id, input: { stateId: $stateId }) { success }
        }
        """
        body = self.query(update_query, variables={"id": issue_id, "stateId": nodes[0]["id"]})
        if body.get("errors") or not common.dot_get(body, "data.issueUpdate.success"):
            raise ValidationError(f"Failed to move the Linear issue to a {state_type} state")

    def issue_state_types(self, identifiers: Sequence[str]) -> dict[str, str]:
        """The workflow state category of each issue, keyed by identifier.

        An identifier that Linear does not return is absent from the result: the issue was
        deleted, the token cannot read it, or it moved to another team and has a new identifier.
        The issues connection answers those cases with no node, where `issue(id:)` answers with
        an error, so a failed request is always a failed request. Raises LinearIntegrationError.
        """
        filters: list[dict[str, Any]] = []
        for identifier in identifiers:
            match = _ISSUE_IDENTIFIER.fullmatch(identifier)
            if match is not None:
                filters.append({"team": {"key": {"eq": match.group(1)}}, "number": {"eq": int(match.group(2))}})
        if not filters:
            return {}

        states_query = """
        query IssueStates($filter: IssueFilter!, $first: Int!) {
            issues(filter: $filter, first: $first, includeArchived: true) {
                nodes { identifier state { type } }
            }
        }
        """
        body = self._read(states_query, variables={"filter": {"or": filters}, "first": len(filters)})
        nodes = common.dot_get(body, "data.issues.nodes")
        if body.get("errors") or not isinstance(nodes, list):
            raise LinearIntegrationError("Failed to read the Linear issue states")
        return {
            node["identifier"]: node["state"]["type"]
            for node in nodes
            if isinstance(node.get("identifier"), str) and isinstance((node.get("state") or {}).get("type"), str)
        }

    def workflow_state_type(self, state_id: str) -> str | None:
        state_query = """
        query WorkflowStateType($id: ID!) {
            workflowStates(filter: { id: { eq: $id } }, first: 1, includeArchived: true) { nodes { type } }
        }
        """
        body = self._read(state_query, variables={"id": state_id})
        nodes = common.dot_get(body, "data.workflowStates.nodes")
        if body.get("errors") or not isinstance(nodes, list):
            raise LinearIntegrationError("Failed to read the Linear workflow state")
        state_type = nodes[0].get("type") if nodes else None
        return state_type if isinstance(state_type, str) else None

    def _read(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """`query`, but a rate-limited answer raises LinearRateLimitedError with the time until Linear resets."""
        response = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {self.integration.sensitive_config['access_token']}"},
            json={"query": query, "variables": variables},
            timeout=10,
        )
        body = response.json()
        error_codes = {
            (error.get("extensions") or {}).get("code") for error in body.get("errors") or [] if isinstance(error, dict)
        }
        if response.status_code == 429 or "RATELIMITED" in error_codes:
            raise LinearRateLimitedError(_rate_limit_wait_seconds(response))
        return body

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
