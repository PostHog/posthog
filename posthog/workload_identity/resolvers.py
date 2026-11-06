"""Look up a workload's immutable subject from the name people know it by, through the provider's API.

Each provider entry in `providers.py` points at one of these. A person types `owner/repo`, and PostHog
stores the repository ID the token carries, so nobody has to find that ID by hand.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit

from django.conf import settings

import requests
import structlog

from posthog.egress.github.transport import GitHubRateLimitError, github_request
from posthog.egress.gitlab.transport import gitlab_request
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.integrations import IntegrationManager
from posthog.models.github_integration_base import GitHubIntegrationError, _is_safe_github_repo_path
from posthog.models.integration.github import GitHubIntegration
from posthog.models.integration.model import Integration
from posthog.workload_identity.subjects import (
    ResolvedWorkloadSubject,
    WorkloadSubjectLookupUnavailable,
    WorkloadSubjectNotFound,
)

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "workload_identity"
GITHUB_REPOSITORY_ENDPOINT = "/repos/{owner}/{repo}"
GITHUB_UNAVAILABLE = "GitHub didn't answer. Try again in a minute, or enter the repository ID by hand."


def _github_subject(body: Any, found_via: str) -> ResolvedWorkloadSubject:
    if not isinstance(body, dict) or not isinstance(body.get("id"), int) or not isinstance(body.get("full_name"), str):
        raise WorkloadSubjectLookupUnavailable(GITHUB_UNAVAILABLE)
    return ResolvedWorkloadSubject(subject=str(body["id"]), subject_name=body["full_name"], found_via=found_via)


def _repository_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise WorkloadSubjectLookupUnavailable(GITHUB_UNAVAILABLE)


def _through_integration(team_id: int, repository: str) -> tuple[ResolvedWorkloadSubject | None, bool]:
    """Ask GitHub through the team's GitHub integrations, which also see the private repositories they were
    installed on. Also says whether an installation couldn't answer, because then a miss proves nothing."""
    unavailable = False
    for integration in Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
        github = GitHubIntegration(integration, source=EGRESS_SOURCE, priority=Priority.NORMAL)
        try:
            response = github.api_request("GET", f"/repos/{repository}", endpoint=GITHUB_REPOSITORY_ENDPOINT)
        except (EgressBudgetExhausted, GitHubRateLimitError, GitHubIntegrationError):
            unavailable = True
            continue
        if response.status_code == 200:
            return _github_subject(_repository_json(response), "your GitHub integration"), unavailable
    return None, unavailable


def _public(repository: str) -> ResolvedWorkloadSubject:
    """Ask GitHub for a public repository, with PostHog's own token when the deployment has one. Without a
    token GitHub allows few requests per IP, so the lookup can fail and the person enters the ID by hand."""
    headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"} if settings.GITHUB_TOKEN else {}
    try:
        response = github_request(
            "GET",
            f"https://api.github.com/repos/{repository}",
            source=EGRESS_SOURCE,
            headers=headers,
            priority=Priority.NORMAL,
            endpoint=GITHUB_REPOSITORY_ENDPOINT,
            timeout=10,
        )
    except requests.RequestException:
        raise WorkloadSubjectLookupUnavailable(GITHUB_UNAVAILABLE)
    not_found = WorkloadSubjectNotFound(
        f"PostHog can't see a GitHub repository named {repository}. For a private repository, connect the "
        "GitHub integration, or enter the repository ID by hand."
    )
    if response.status_code == 404:
        raise not_found
    if response.status_code != 200:
        logger.info("workload_github_repository_lookup_failed", status_code=response.status_code)
        raise WorkloadSubjectLookupUnavailable(GITHUB_UNAVAILABLE)
    body = _repository_json(response)
    # PostHog's token may see repositories that aren't public, and only a team's own integration may
    # tell a team about those.
    if not isinstance(body, dict) or body.get("private") is not False:
        raise not_found
    return _github_subject(body, "GitHub")


_GITHUB_REMOTE_PREFIX = re.compile(r"^(?:(?:https?://|ssh://git@|git@)?github\.com[:/])", re.IGNORECASE)


def resolve_github_repository(team_id: int, name: str) -> ResolvedWorkloadSubject:
    repository = _GITHUB_REMOTE_PREFIX.sub("", name.strip()).removesuffix(".git").strip("/")
    # The name goes into an authenticated GitHub URL, so anything but owner/repo could reach another endpoint.
    if not _is_safe_github_repo_path(repository):
        raise WorkloadSubjectNotFound("Enter the repository as owner/repo, like posthog/posthog.")
    found, integration_unavailable = _through_integration(team_id, repository)
    if found:
        return found
    try:
        return _public(repository)
    except WorkloadSubjectNotFound:
        # A private repository an installation would have seen looks missing while that installation is down.
        if integration_unavailable:
            raise WorkloadSubjectLookupUnavailable(GITHUB_UNAVAILABLE)
        raise


GITLAB_COM = "https://gitlab.com"
GITLAB_PROJECT_ENDPOINT = "/api/v4/projects/{id}"
GITLAB_UNAVAILABLE = "GitLab didn't answer. Try again in a minute, or enter the project ID by hand."
# A GitLab path is a namespace, any number of subgroups, and a project name.
_GITLAB_PROJECT_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$")
_GITLAB_REMOTE_PREFIX = re.compile(r"^(?:(?:https?://|ssh://git@|git@)?gitlab\.com[:/])", re.IGNORECASE)


def _gitlab_project(token: str | None, path: str) -> requests.Response:
    return gitlab_request(
        "GET",
        f"{GITLAB_COM}/api/v4/projects/{quote(path, safe='')}",
        token=token,
        source=EGRESS_SOURCE,
        endpoint=GITLAB_PROJECT_ENDPOINT,
        allow_redirects=False,
        timeout=10,
    )


def _gitlab_subject(response: requests.Response, found_via: str) -> ResolvedWorkloadSubject | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("id"), int):
        return None
    path = body.get("path_with_namespace")
    # PostHog's token may see projects that aren't public, and only a team's own integration may tell a
    # team about those. An anonymous request only ever sees public ones.
    if not isinstance(path, str) or (found_via == "GitLab" and body.get("visibility") != "public"):
        return None
    return ResolvedWorkloadSubject(subject=str(body["id"]), subject_name=path, found_via=found_via)


def _gitlab_through_integration(team_id: int, path: str) -> tuple[ResolvedWorkloadSubject | None, bool]:
    unavailable = False
    for integration in IntegrationManager.gitlab.token.list(team_id):
        hostname = urlsplit(str(integration.config.get("hostname") or "")).hostname or ""
        token = integration.sensitive_config.get("access_token")
        # Only gitlab.com issues tokens PostHog trusts, and a self-managed instance's token must not go there.
        if hostname.lower() != "gitlab.com" or not token:
            continue
        try:
            response = _gitlab_project(token, path)
        except requests.RequestException:
            unavailable = True
            continue
        if response.status_code == 200 and (found := _gitlab_subject(response, "your GitLab integration")):
            return found, unavailable
        unavailable = unavailable or response.status_code not in (200, 404)
    return None, unavailable


def resolve_gitlab_project(team_id: int, name: str) -> ResolvedWorkloadSubject:
    path = _GITLAB_REMOTE_PREFIX.sub("", name.strip()).split("/-/")[0].removesuffix(".git").strip("/")
    if ".." in path or not _GITLAB_PROJECT_PATH.fullmatch(path):
        raise WorkloadSubjectNotFound("Enter the project path, like group/project or group/subgroup/project.")
    found, unavailable = _gitlab_through_integration(team_id, path)
    if found:
        return found
    try:
        response = _gitlab_project(settings.GITLAB_TOKEN or None, path)
    except requests.RequestException:
        raise WorkloadSubjectLookupUnavailable(GITLAB_UNAVAILABLE)
    if response.status_code == 200 and (found := _gitlab_subject(response, "GitLab")):
        return found
    if unavailable or response.status_code not in (200, 401, 404):
        logger.info("workload_gitlab_project_lookup_failed", status_code=response.status_code)
        raise WorkloadSubjectLookupUnavailable(GITLAB_UNAVAILABLE)
    raise WorkloadSubjectNotFound(
        f"PostHog can't see a GitLab project at {path}. For a private project, connect a GitLab integration that "
        "can read it, or enter the project ID by hand."
    )
