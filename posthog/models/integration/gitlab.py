"""GitLab integration."""

import re
from typing import Any, Literal
from urllib.parse import urlencode, urlparse

import requests

from posthog.dataclasses import frozen
from posthog.egress.gitlab.transport import gitlab_request
from posthog.egress.observability.observability import default_normalize_endpoint
from posthog.integrations.contracts import IntegrationRecord
from posthog.security.url_validation import is_url_allowed

from . import common, model
from .assignees import MAX_ASSIGNEES, Assignee, AssigneeLookupFailed


class GitLabIntegrationError(Exception):
    pass


# Caps one listing at 1,000 projects so that a token with access to a whole instance stays cheap.
MAX_PROJECT_PAGES = 10


@frozen
class GitLabProject:
    id: int
    path_with_namespace: str
    web_url: str
    default_branch: str | None


@frozen
class GitLabMergeRequest:
    iid: int
    web_url: str
    state: Literal["opened", "closed", "locked", "merged"]
    draft: bool


class GitLabIntegration:
    integration: model.Integration

    @staticmethod
    def _validate_api_url(url: str) -> None:
        if urlparse(url).scheme != "https":
            raise GitLabIntegrationError("Invalid GitLab hostname: HTTPS is required")
        allowed, error = is_url_allowed(url)
        if not allowed:
            raise GitLabIntegrationError(f"Invalid GitLab hostname: {error}")

    @staticmethod
    def _request(
        method: str, hostname: str, path: str, access_token: str, *, endpoint: str | None = None, **kwargs: Any
    ) -> requests.Response:
        url = f"{hostname}/api/v4/{path}"
        GitLabIntegration._validate_api_url(url)
        return gitlab_request(
            method,
            url,
            token=access_token,
            source="integration",
            endpoint=endpoint or default_normalize_endpoint(url),
            # disallow redirects to prevent SSRF on redirected host
            allow_redirects=False,
            timeout=10,
            **kwargs,
        )

    @staticmethod
    def get(hostname: str, endpoint: str, project_access_token: str) -> dict:
        return GitLabIntegration._request("GET", hostname, endpoint, project_access_token).json()

    @staticmethod
    def post(hostname: str, endpoint: str, project_access_token: str, json: dict) -> dict:
        return GitLabIntegration._request("POST", hostname, endpoint, project_access_token, json=json).json()

    @classmethod
    def create_integration(cls, hostname, project_id, project_access_token, team_id, user) -> model.Integration:
        project = cls.get(hostname, f"projects/{project_id}", project_access_token)

        integration = model.Integration.objects.create(
            team_id=team_id,
            kind=model.Integration.IntegrationKind.GITLAB,
            integration_id=project.get("name_with_namespace"),
            config={
                "hostname": hostname,
                "path_with_namespace": project.get("path_with_namespace"),
                "project_id": project.get("id"),
            },
            sensitive_config={"access_token": project_access_token},
            created_by=user,
        )

        return integration

    def __init__(self, integration: IntegrationRecord) -> None:
        if integration.kind != "gitlab":
            raise Exception("GitLabIntegration init called with Integration with wrong 'kind'")
        self.integration = model.integration_model(integration)

    @property
    def project_path(self) -> str:
        return common.dot_get(self.integration.config, "path_with_namespace")

    @property
    def hostname(self) -> str:
        return common.dot_get(self.integration.config, "hostname")

    def list_assignees(self, search: str = "") -> list[Assignee]:
        """Active members of the connected project, including inherited ones, matching ``search``."""
        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")

        params: dict[str, str | int] = {"state": "active", "per_page": MAX_ASSIGNEES}
        if search.strip():
            params["query"] = search.strip()
        query = urlencode(params)
        # This endpoint answers with a JSON array, unlike the objects `get` is typed for.
        members: object = GitLabIntegration.get(hostname, f"projects/{project_id}/members/all?{query}", access_token)
        if not isinstance(members, list):
            # GitLab reports failures as an object such as {"message": "403 Forbidden"}.
            error = members.get("message") or members.get("error") if isinstance(members, dict) else None
            raise AssigneeLookupFailed(f"Failed to list the GitLab project's members: {error or 'unexpected response'}")
        # The state query filter only applies on paid GitLab tiers, so filter here as well.
        return [
            Assignee(id=str(member["id"]), name=member.get("name") or member["username"])
            for member in members
            if member.get("state", "active") == "active"
        ]

    def create_issue(self, config: dict[str, str]):
        title: str = config.pop("title")
        description: str = config.pop("body")
        assignee = config.pop("assignee", None)

        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")

        payload: dict[str, Any] = {
            "title": title,
            "description": description,
            "labels": "posthog",
        }
        if assignee:
            payload["assignee_ids"] = [int(assignee)]

        issue = GitLabIntegration.post(
            hostname,
            f"projects/{project_id}/issues",
            access_token,
            payload,
        )

        return {"issue_id": issue["iid"]}

    def close_issue(self, issue_id: int) -> None:
        """Close an issue in the connected project. Raises on failure."""
        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")

        response = self._request(
            "PUT", hostname, f"projects/{project_id}/issues/{issue_id}", access_token, json={"state_event": "close"}
        )
        if response.status_code != 200:
            raise GitLabIntegrationError(f"GitLabIntegration: failed to close issue: {response.text[:300]}")

    def _get_issue_by_iid(self, issue_iid: int) -> dict[str, Any] | None:
        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")
        response = self._request("GET", hostname, f"projects/{project_id}/issues/{issue_iid}", access_token)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitLabIntegrationError(
                f"GitLabIntegration: failed to retrieve issue: {response.text[:300]}",
            )
        issue = response.json()
        return issue if isinstance(issue, dict) else None

    @staticmethod
    def _issue_results(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for issue in issues:
            iid = issue.get("iid")
            if iid is None:
                continue
            results.append(
                {
                    "id": str(iid),
                    "title": issue.get("title") or f"#{iid}",
                    "url": issue.get("web_url") or "",
                    # Matches the shape GitLabIntegration.create_issue stores.
                    "external_context": {"issue_id": iid},
                }
            )
        return results

    def search_issues(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Search existing GitLab issues in the connected project for the link-existing flow."""
        issue_id_match = re.fullmatch(r"#?([1-9][0-9]{0,9})", query.strip())
        if issue_id_match:
            issue = self._get_issue_by_iid(int(issue_id_match.group(1)))
            if issue:
                return self._issue_results([issue])

        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")
        # A blank query lists the project's recent issues instead of filtering.
        params: dict[str, str | int] = {"per_page": limit, "order_by": "updated_at"}
        if query.strip():
            params["search"] = query
            params["in"] = "title"
        response = self._request("GET", hostname, f"projects/{project_id}/issues", access_token, params=params)
        if response.status_code != 200:
            raise GitLabIntegrationError(
                f"GitLabIntegration: failed to search issues: {response.text[:300]}",
            )
        issues = response.json()
        if not isinstance(issues, list):
            return []

        return self._issue_results(issues)

    def list_projects(self, search: str = "") -> list[GitLabProject]:
        """Projects the token can push to, most recently active first."""
        hostname = self.integration.config.get("hostname")
        access_token = self.integration.sensitive_config.get("access_token")

        # Developer (30) is the lowest role that can push a branch.
        params: dict[str, str | int] = {
            "membership": "true",
            "min_access_level": 30,
            "archived": "false",
            "simple": "true",
            "order_by": "last_activity_at",
            "per_page": 100,
        }
        if search.strip():
            params["search"] = search.strip()

        projects: list[GitLabProject] = []
        page = "1"
        for _ in range(MAX_PROJECT_PAGES):
            response = self._request(
                "GET", hostname, "projects", access_token, endpoint="/api/v4/projects", params={**params, "page": page}
            )
            if response.status_code != 200:
                raise GitLabIntegrationError(f"GitLabIntegration: failed to list projects: {response.text[:300]}")
            projects.extend(
                GitLabProject(
                    id=project["id"],
                    path_with_namespace=project["path_with_namespace"],
                    web_url=project["web_url"],
                    default_branch=project.get("default_branch"),
                )
                for project in response.json()
            )
            page = response.headers.get("X-Next-Page", "")
            if not page:
                break
        return projects

    @staticmethod
    def _merge_request(payload: dict[str, Any]) -> GitLabMergeRequest:
        return GitLabMergeRequest(
            iid=payload["iid"], web_url=payload["web_url"], state=payload["state"], draft=bool(payload.get("draft"))
        )

    def create_merge_request(
        self, project_id: int, *, source_branch: str, target_branch: str, title: str, description: str
    ) -> GitLabMergeRequest:
        """Open a draft merge request. Raises on failure."""
        hostname = self.integration.config.get("hostname")
        access_token = self.integration.sensitive_config.get("access_token")

        response = self._request(
            "POST",
            hostname,
            f"projects/{project_id}/merge_requests",
            access_token,
            endpoint="/api/v4/projects/{id}/merge_requests",
            # GitLab marks a merge request as a draft from the title prefix.
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": f"Draft: {title}",
                "description": description,
            },
        )
        if response.status_code != 201:
            raise GitLabIntegrationError(f"GitLabIntegration: failed to create merge request: {response.text[:300]}")
        return self._merge_request(response.json())

    def get_merge_request(self, project_id: int, merge_request_iid: int) -> GitLabMergeRequest | None:
        hostname = self.integration.config.get("hostname")
        access_token = self.integration.sensitive_config.get("access_token")

        response = self._request(
            "GET",
            hostname,
            f"projects/{project_id}/merge_requests/{merge_request_iid}",
            access_token,
            endpoint="/api/v4/projects/{id}/merge_requests/{iid}",
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitLabIntegrationError(f"GitLabIntegration: failed to retrieve merge request: {response.text[:300]}")
        return self._merge_request(response.json())
