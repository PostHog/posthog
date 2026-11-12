"""GitLab integration."""

import re
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlparse

import requests

from posthog.dataclasses import frozen
from posthog.egress.gitlab.transport import gitlab_request
from posthog.integrations.contracts import IntegrationRecord
from posthog.integrations.enums import IntegrationAuthType
from posthog.security.url_validation import is_url_allowed

from . import common, model, row_writes
from .assignees import MAX_ASSIGNEES, Assignee, AssigneeLookupFailed
from .auth_types import effective_auth_type


class GitLabIntegrationError(Exception):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        # A 429 or 5xx from GitLab, which a retry can get past.
        self.transient = transient


# Caps one listing at 1,000 projects so that a token with access to a whole instance stays cheap.
MAX_PROJECT_PAGES = 10

# Developer is the lowest role that can push a branch.
DEVELOPER_ACCESS_LEVEL = 30

# Coding tasks open merge requests through the API, and GitLab also accepts this scope for git over HTTPS.
TASK_REQUIRED_SCOPES = ("api",)


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


@frozen
class GitLabAccessToken:
    token: str
    # None when the token does not expire during a run, so the sandbox never asks for a new one.
    refresh_after_seconds: float | None


@frozen
class GitLabTokenInfo:
    scopes: tuple[str, ...]
    expires_at: date | None

    @property
    def missing_task_scopes(self) -> tuple[str, ...]:
        return tuple(scope for scope in TASK_REQUIRED_SCOPES if scope not in self.scopes)


class GitLabCredentialSource(ABC):
    """The only place that knows how a GitLab connection authenticates.

    Callers send the token as a Bearer token and clone with `oauth2:<token>`. GitLab accepts both
    forms for every token type, so a new auth type needs only a new source.
    """

    @abstractmethod
    def access_token(self) -> GitLabAccessToken: ...

    @abstractmethod
    def describe(self, *, timeout: float = 10) -> GitLabTokenInfo | None:
        """The scopes and expiry of the token, or None when GitLab does not report them."""


class PastedTokenSource(GitLabCredentialSource):
    """A project, group or personal access token that a person pasted into the connect form."""

    def __init__(self, hostname: str, token: str) -> None:
        self._hostname = hostname
        self._token = token

    def access_token(self) -> GitLabAccessToken:
        return GitLabAccessToken(token=self._token, refresh_after_seconds=None)

    def describe(self, *, timeout: float = 10) -> GitLabTokenInfo | None:
        try:
            response = GitLabIntegration._request(
                "GET",
                self._hostname,
                "personal_access_tokens/self",
                self._token,
                endpoint="/api/v4/personal_access_tokens/self",
                scoped=False,
                timeout=timeout,
            )
        except requests.RequestException:
            return None
        # Instances older than GitLab 15.5 have no such endpoint.
        if response.status_code != 200:
            return None
        payload = GitLabIntegration._json(response)
        if not isinstance(payload, dict):
            return None
        expires_at = payload.get("expires_at")
        return GitLabTokenInfo(
            scopes=tuple(scope for scope in payload.get("scopes") or [] if isinstance(scope, str)),
            expires_at=date.fromisoformat(expires_at) if isinstance(expires_at, str) else None,
        )


class GitLabIntegration:
    integration: model.Integration

    @staticmethod
    def _validate_api_url(url: str) -> None:
        if urlparse(url).scheme != "https":
            raise GitLabIntegrationError("Invalid GitLab hostname: HTTPS is required")
        allowed, _ = is_url_allowed(url)
        if not allowed:
            # The validator's reason names the IP the hostname resolved to, and setup surfaces this
            # error to the API caller, so the detail stays in the url_validation.blocked log line.
            raise GitLabIntegrationError("Invalid GitLab hostname: it must be a publicly reachable GitLab instance")

    @staticmethod
    def _request(
        method: str,
        hostname: str,
        path: str,
        access_token: str,
        *,
        endpoint: str,
        scoped: bool = True,
        timeout: float = 10,
        **kwargs: Any,
    ) -> requests.Response:
        """``endpoint`` is the template for the metric label. A project id can be an encoded path
        such as ``group%2Frepo``, so the path itself is customer data and never becomes a label."""
        url = f"{hostname}/api/v4/{path}"
        GitLabIntegration._validate_api_url(url)
        return gitlab_request(
            method,
            url,
            token=access_token,
            source="integration",
            endpoint=endpoint,
            scoped=scoped,
            # disallow redirects to prevent SSRF on redirected host
            allow_redirects=False,
            timeout=timeout,
            **kwargs,
        )

    @staticmethod
    def _json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError as error:
            raise GitLabIntegrationError(
                f"GitLab returned a response that isn't JSON (HTTP {response.status_code}). "
                "Check that the hostname points to a GitLab instance."
            ) from error

    @staticmethod
    def get(hostname: str, path: str, project_access_token: str, *, endpoint: str) -> dict:
        return GitLabIntegration._json(
            GitLabIntegration._request("GET", hostname, path, project_access_token, endpoint=endpoint)
        )

    @staticmethod
    def post(hostname: str, path: str, project_access_token: str, json: dict, *, endpoint: str) -> dict:
        return GitLabIntegration._json(
            GitLabIntegration._request("POST", hostname, path, project_access_token, endpoint=endpoint, json=json)
        )

    @classmethod
    def create_integration(cls, hostname, project_id, project_access_token, team_id, user) -> IntegrationRecord:
        try:
            response = cls._request(
                "GET",
                hostname,
                f"projects/{project_id}",
                project_access_token,
                endpoint="/api/v4/projects/{id}",
                # Setup runs on a token the caller supplied and PostHog may never store, so this
                # probe must not mint a metric scope per rejected token.
                scoped=False,
            )
        except requests.RequestException as error:
            raise GitLabIntegrationError("Couldn't connect to GitLab. Check the hostname and try again.") from error
        if response.status_code != 200:
            raise GitLabIntegrationError(
                f"GitLab returned HTTP {response.status_code} for this project. "
                "Check the hostname, project ID, and access token."
            )
        project = cls._json(response)

        config: dict[str, Any] = {
            "hostname": hostname,
            "path_with_namespace": project.get("path_with_namespace"),
            "project_id": project.get("id"),
        }
        token_info = PastedTokenSource(hostname, project_access_token).describe()
        if token_info is not None:
            config["token_scopes"] = list(token_info.scopes)
            config["token_expires_at"] = token_info.expires_at.isoformat() if token_info.expires_at else None

        integration = row_writes.creator_accessor(model.Integration.IntegrationKind.GITLAB.value).create(
            team_id,
            external_id=project.get("name_with_namespace"),
            config=config,
            sensitive_config={"access_token": project_access_token},
            created_by_id=user.id if user else None,
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

    @property
    def credentials(self) -> GitLabCredentialSource:
        auth_type = effective_auth_type(self.integration.kind, self.integration.config)
        if auth_type != IntegrationAuthType.TOKEN:
            raise GitLabIntegrationError(f"GitLab connections with auth type {auth_type} have no API access")
        return PastedTokenSource(self.hostname, self.integration.sensitive_config.get("access_token") or "")

    def _access_token(self) -> str:
        return self.credentials.access_token().token

    def list_assignees(self, search: str = "") -> list[Assignee]:
        """Active members of the connected project, including inherited ones, matching ``search``."""
        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self._access_token()

        params: dict[str, str | int] = {"state": "active", "per_page": MAX_ASSIGNEES}
        if search.strip():
            params["query"] = search.strip()
        query = urlencode(params)
        # This endpoint answers with a JSON array, unlike the objects `get` is typed for.
        members: object = GitLabIntegration.get(
            hostname,
            f"projects/{project_id}/members/all?{query}",
            access_token,
            endpoint="/api/v4/projects/{id}/members/all",
        )
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
        access_token = self._access_token()

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
            endpoint="/api/v4/projects/{id}/issues",
        )

        return {"issue_id": issue["iid"]}

    def close_issue(self, issue_id: int) -> None:
        """Close an issue in the connected project. Raises on failure."""
        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self._access_token()

        response = self._request(
            "PUT",
            hostname,
            f"projects/{project_id}/issues/{issue_id}",
            access_token,
            endpoint="/api/v4/projects/{id}/issues/{iid}",
            json={"state_event": "close"},
        )
        if response.status_code != 200:
            raise GitLabIntegrationError(f"GitLabIntegration: failed to close issue: {response.text[:300]}")

    def _get_issue_by_iid(self, issue_iid: int) -> dict[str, Any] | None:
        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self._access_token()
        response = self._request(
            "GET",
            hostname,
            f"projects/{project_id}/issues/{issue_iid}",
            access_token,
            endpoint="/api/v4/projects/{id}/issues/{iid}",
        )
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
        access_token = self._access_token()
        # A blank query lists the project's recent issues instead of filtering.
        params: dict[str, str | int] = {"per_page": limit, "order_by": "updated_at"}
        if query.strip():
            params["search"] = query
            params["in"] = "title"
        response = self._request(
            "GET",
            hostname,
            f"projects/{project_id}/issues",
            access_token,
            endpoint="/api/v4/projects/{id}/issues",
            params=params,
        )
        if response.status_code != 200:
            raise GitLabIntegrationError(
                f"GitLabIntegration: failed to search issues: {response.text[:300]}",
            )
        issues = response.json()
        if not isinstance(issues, list):
            return []

        return self._issue_results(issues)

    def list_projects(self, search: str = "", *, deadline: float | None = None) -> list[GitLabProject]:
        """Projects the token can push to, most recently active first."""
        hostname = self.integration.config.get("hostname")
        access_token = self._access_token()

        params: dict[str, str | int] = {
            "membership": "true",
            "min_access_level": DEVELOPER_ACCESS_LEVEL,
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
            remaining = deadline - time.monotonic() if deadline is not None else 10.0
            if remaining <= 0:
                raise GitLabIntegrationError("Could not load GitLab projects in time. Try again.")
            response = self._request(
                "GET",
                hostname,
                "projects",
                access_token,
                endpoint="/api/v4/projects",
                params={**params, "page": page},
                timeout=min(10.0, remaining),
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
                for project in self._json(response)
            )
            page = response.headers.get("X-Next-Page", "")
            if not page:
                break
        return projects

    def get_pushable_project(self, project_path: str, *, timeout: float = 10) -> GitLabProject | None:
        """The project at ``project_path``, or None when it is missing or the token cannot push to it."""
        response = self._request(
            "GET",
            self.hostname,
            f"projects/{quote(project_path, safe='')}",
            self._access_token(),
            endpoint="/api/v4/projects/{id}",
            timeout=timeout,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitLabIntegrationError(
                f"GitLabIntegration: failed to retrieve project: {response.text[:300]}",
                transient=response.status_code == 429 or response.status_code >= 500,
            )
        project = self._json(response)
        permissions = project.get("permissions") or {}
        access_level = max(
            (permissions.get("project_access") or {}).get("access_level") or 0,
            (permissions.get("group_access") or {}).get("access_level") or 0,
        )
        if access_level < DEVELOPER_ACCESS_LEVEL:
            return None
        return GitLabProject(
            id=project["id"],
            path_with_namespace=project["path_with_namespace"],
            web_url=project["web_url"],
            default_branch=project.get("default_branch"),
        )

    def _get_json_or_raise(self, path: str, *, endpoint: str, timeout: float) -> Any:
        response = self._request("GET", self.hostname, path, self._access_token(), endpoint=endpoint, timeout=timeout)
        if response.status_code in (401, 403, 404):
            return None
        if response.status_code != 200:
            raise GitLabIntegrationError(
                f"GitLabIntegration: failed to read {endpoint}: {response.text[:300]}",
                transient=response.status_code == 429 or response.status_code >= 500,
            )
        return self._json(response)

    def token_reaches_only_connected_project(self, *, timeout: float = 10) -> bool:
        """Whether the token is an access token of the connected project.

        The sandbox holds the token, and a personal or group token can reach more than this project.
        A username can be registered by anyone, so the proof is the project's own token list: the
        token's id must appear there with the same bot user. Any answer GitLab refuses counts as no.
        """
        connected_id = self.integration.config.get("project_id")
        if connected_id is None:
            return False
        user = self._get_json_or_raise("user", endpoint="/api/v4/user", timeout=timeout)
        if not isinstance(user, dict) or user.get("bot") is not True:
            return False
        username = user.get("username")
        if not isinstance(username, str) or not username.startswith(f"project_{connected_id}_bot"):
            return False
        token = self._get_json_or_raise(
            "personal_access_tokens/self", endpoint="/api/v4/personal_access_tokens/self", timeout=timeout
        )
        if not isinstance(token, dict) or token.get("id") is None:
            return False
        project_token = self._get_json_or_raise(
            f"projects/{connected_id}/access_tokens/{token['id']}",
            endpoint="/api/v4/projects/{id}/access_tokens/{token_id}",
            timeout=timeout,
        )
        return (
            isinstance(project_token, dict)
            and project_token.get("user_id") is not None
            and project_token.get("user_id") == user.get("id") == token.get("user_id")
        )

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
        access_token = self._access_token()

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
        return self._merge_request(self._json(response))

    def get_merge_request(self, project_id: int, merge_request_iid: int) -> GitLabMergeRequest | None:
        hostname = self.integration.config.get("hostname")
        access_token = self._access_token()

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
        return self._merge_request(self._json(response))
