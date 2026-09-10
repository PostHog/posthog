"""GitHub App integration: installation access, repository content and PR operations."""

import re
import time
import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.conf import settings

import requests
import structlog

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority
from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers
from posthog.sync import database_sync_to_async

from . import common, model, refresh_tracking

logger = structlog.get_logger(__name__)


# `owner/repo`, single slash, no traversal. Used to keep repo/ref/sha values out of GitHub API URL
# paths where a crafted value (e.g. `../../other-repo/contents/x?ref=y`) could redirect the
# authenticated request to a different endpoint.
_GITHUB_REPO_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

_GITHUB_REF_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")

_GITHUB_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Upper bound on the diff text we return, to keep a pathological diff (generated/vendored
# files) from bloating the JSON response and worker memory. ~1 MB of text.
_MAX_DIFF_CHARS = 1_000_000


def _is_safe_github_repo_path(repo_path: str) -> bool:
    return ".." not in repo_path and bool(_GITHUB_REPO_PATH_RE.fullmatch(repo_path))


def _is_safe_github_ref(ref: str) -> bool:
    """A git ref safe to interpolate into a GitHub API URL path (no traversal / URL-control chars)."""
    return (
        bool(ref)
        and ".." not in ref
        and not ref.startswith("/")
        and not ref.endswith("/")
        and bool(_GITHUB_REF_RE.fullmatch(ref))
    )


def _is_safe_github_sha(sha: str) -> bool:
    return bool(_GITHUB_COMMIT_SHA_RE.fullmatch(sha))


# Default branches change rarely; a multi-hour TTL is plenty to avoid hitting
# GitHub on every paginated branch request while keeping the window in which a
# renamed default branch stays stale tolerably short.
GITHUB_DEFAULT_BRANCH_CACHE_TTL_SECONDS = 60 * 60 * 6

GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS = 30


@dataclass(frozen=True)
class GitHubUserAuthorization:
    """Outcome of a successful GitHub App user authorization code exchange."""

    gh_id: int
    gh_login: str
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    access_token_expires_in: int | None
    refresh_token_expires_in: int | None


@dataclass(frozen=True)
class GitHubInstallationAccess:
    """Installation-level access token response for a GitHub App installation."""

    installation_id: str
    installation_info: dict[str, Any]
    access_token: str = field(repr=False)
    token_expires_at: str  # ISO datetime returned by GitHub, e.g. "2024-01-01T14:00:00Z"
    repository_selection: str


class GitHubInstallationAccessFetchError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def invalidate_github_repository_caches_for_installation(installation_id: str | int) -> None:
    """Affects both team Integration and personal UserIntegration rows."""
    from posthog.models.user_integration import UserIntegration

    installation_id_str = str(installation_id)
    model.Integration.objects.filter(kind="github", integration_id=installation_id_str).update(
        repository_cache_updated_at=None
    )
    UserIntegration.objects.filter(
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=installation_id_str,
    ).update(repository_cache_updated_at=None)


def github_account_type(owner_type: str | None) -> str | None:
    """Normalize GitHub's account ``type`` ("Organization" / "User") to org vs personal."""
    if owner_type == "Organization":
        return "organization"
    if owner_type == "User":
        return "personal"
    return None


class GitHubIntegration(GitHubIntegrationBase):
    integration: model.Integration

    @classmethod
    def fetch_installation_access(cls, installation_id: str) -> GitHubInstallationAccess:
        try:
            installation_info_response = cls.client_request(f"installations/{installation_id}")
            access_token_response = cls.client_request(f"installations/{installation_id}/access_tokens", method="POST")
        except Exception as exc:
            raise GitHubInstallationAccessFetchError("installation_fetch_failed") from exc

        # A non-200 body here is an error envelope without `account`, and callers persist
        # `account.login` as the display name; failing keeps the numeric installation id out of the UI.
        if installation_info_response.status_code != 200:
            logger.warning(
                "GitHubIntegration: failed to fetch installation info",
                installation_id=installation_id,
                status_code=installation_info_response.status_code,
            )
            raise GitHubInstallationAccessFetchError("installation_fetch_failed")

        try:
            installation_info = installation_info_response.json()
            access_token_data = access_token_response.json()
        except ValueError as exc:
            raise GitHubInstallationAccessFetchError("installation_fetch_failed") from exc

        installation_access_token = access_token_data.get("token")
        token_expires_at = access_token_data.get("expires_at")
        if access_token_response.status_code != 201 or not installation_access_token or not token_expires_at:
            raise GitHubInstallationAccessFetchError("installation_token_failed")

        return GitHubInstallationAccess(
            installation_id=installation_id,
            installation_info=installation_info,
            access_token=installation_access_token,
            token_expires_at=token_expires_at,
            repository_selection=access_token_data.get("repository_selection", "selected"),
        )

    @classmethod
    def integration_from_installation_id(
        cls, installation_id: str, team_id: int, created_by: User | None = None
    ) -> model.Integration:
        installation_access = cls.fetch_installation_access(installation_id)
        now = int(time.time())
        expires_in = int(datetime.fromisoformat(installation_access.token_expires_at).timestamp() - now)

        config = {
            "installation_id": installation_id,
            "expires_in": expires_in,
            "refreshed_at": now,
            "repository_selection": installation_access.repository_selection,
            "account": {
                "type": common.dot_get(installation_access.installation_info, "account.type", None),
                "name": common.dot_get(installation_access.installation_info, "account.login", installation_id),
            },
        }
        # See GitHubIntegrationBase.refresh_access_token for why permissions are persisted.
        permissions = installation_access.installation_info.get("permissions")
        if isinstance(permissions, dict):
            config["permissions"] = permissions

        sensitive_config = {"access_token": installation_access.access_token}

        integration, created = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind="github",
            integration_id=installation_id,
            defaults={
                "config": config,
                "sensitive_config": sensitive_config,
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        # Every other kind reports this from IntegrationSerializer.create(). GitHub also gets created
        # through its App installation callback and through agentic provisioning, which never reach
        # that serializer, so this is the one place every GitHub connect passes through.
        # IntegrationSerializer.create() skips github for the same reason: its own github branch ends
        # up here, and reporting in both would count one connection twice.
        if created and created_by is not None:
            from posthog.event_usage import (  # noqa: PLC0415 — posthog.event_usage imports posthog.models
                report_user_action,
            )

            owner_type = common.dot_get(installation_access.installation_info, "account.type", None)
            try:
                report_user_action(
                    created_by,
                    "integration created",
                    {
                        "integration_kind": "github",
                        "is_overwrite": False,
                        "repo_owner_type": owner_type,
                        "account_type": github_account_type(owner_type),
                    },
                    team=integration.team,
                )
            except Exception:
                # The integration row is already committed. Raising here would report a connection
                # that actually succeeded as a failure.
                logger.exception("github_integration: failed to report integration created")

        invalidate_github_repository_caches_for_installation(installation_id)

        return integration

    @classmethod
    def github_login_from_code(cls, code: str) -> str | None:
        result = cls.github_user_from_code(code)
        return result.gh_login if result else None

    @classmethod
    def github_user_from_code(cls, code: str, *, redirect_uri: str | None = None) -> "GitHubUserAuthorization | None":
        """Exchange an OAuth code from the GitHub App user authorization flow.

        Pass ``redirect_uri`` when the user was sent to ``/login/oauth/authorize`` with
        the same redirect URI (required by GitHub for the token exchange in that flow).

        Returns a :class:`GitHubUserAuthorization` with the user's id/login plus the
        user-to-server access/refresh tokens and their expirations, or ``None`` if
        the exchange fails or the response lacks an id/login.
        """
        client_id = settings.GITHUB_APP_CLIENT_ID
        client_secret = settings.GITHUB_APP_CLIENT_SECRET
        if not client_id or not client_secret:
            logger.warning("GitHubIntegration: GITHUB_APP_CLIENT_ID/SECRET not configured, cannot exchange code")
            return None

        token_body: dict[str, str] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        }
        if redirect_uri is not None:
            token_body["redirect_uri"] = redirect_uri

        token_response = requests.post(
            "https://github.com/login/oauth/access_token",
            json=token_body,
            headers={"Accept": "application/json"},
            timeout=10,
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            logger.warning(
                "GitHubIntegration: code exchange returned no access_token",
                status_code=token_response.status_code,
                error=token_data.get("error"),
                error_description=token_data.get("error_description"),
                error_uri=token_data.get("error_uri"),
            )
            return None

        # Identity-blind: a fresh user OAuth token with no installation budget behind it.
        user_response = github_request(
            "GET",
            "https://api.github.com/user",
            source="integration",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if user_response.status_code != 200:
            logger.warning("GitHubIntegration: /user request failed", status_code=user_response.status_code)
            return None

        payload = user_response.json()
        gh_id = payload.get("id")
        gh_login = payload.get("login")
        if gh_id is None or not gh_login:
            return None
        access_expires_in = token_data.get("expires_in")
        refresh_expires_in = token_data.get("refresh_token_expires_in")
        return GitHubUserAuthorization(
            gh_id=int(gh_id),
            gh_login=str(gh_login),
            access_token=str(access_token),
            refresh_token=token_data.get("refresh_token") or None,
            access_token_expires_in=int(access_expires_in) if access_expires_in is not None else None,
            refresh_token_expires_in=int(refresh_expires_in) if refresh_expires_in is not None else None,
        )

    @classmethod
    def first_for_team_repository(
        cls,
        team_id: int,
        repository: str,
        *,
        source: str | None = None,
        priority: Priority | None = None,
    ) -> "GitHubIntegration | None":
        """First GitHub integration for the team whose installation can access ``repository`` (``owner/name``).

        ``repository`` reaches us from team-writable content (e.g. artefact payloads), and the access
        check below interpolates it into an authenticated ``GET /repos/{repository}``. Reject anything
        that isn't a plain ``owner/repo`` first, so a crafted value (``owner/repo/contents/x?ref=y``)
        can't steer that authenticated request to a different GitHub endpoint as a probe.
        """
        if not _is_safe_github_repo_path(repository):
            return None
        for integration in model.Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
            github = cls(integration, source=source, priority=priority)
            if github.installation_can_access_repository(repository):
                return github
        return None

    def __init__(
        self, integration: model.Integration, *, source: str | None = None, priority: Priority | None = None
    ) -> None:
        if integration.kind != "github":
            raise Exception("GitHubIntegration init called with Integration with wrong 'kind'")
        self.integration = integration
        if source is not None:
            self.source = source
        if priority is not None:
            self.priority = priority

    def _on_token_refresh_failed(self, response: requests.Response) -> None:
        logger.warning(f"Failed to refresh token for {self}", response=response.text)
        self.integration.errors = common.ERROR_TOKEN_REFRESH_FAILED
        # A permanently-gone installation (uninstalled/suspended) drops expires_in/refreshed_at so the
        # every-minute beat loop stops re-minting it; the errors + config change persist in one save.
        self._disarm_proactive_refresh_if_installation_gone(response)
        reason = (
            refresh_tracking.REFRESH_FAILURE_REASON_HTTP_5XX
            if response.status_code >= 500
            else refresh_tracking.REFRESH_FAILURE_REASON_OTHER
        )
        attempt = refresh_tracking.record_refresh_failure(self.integration, reason=reason)
        refresh_tracking.oauth_refresh_counter.labels(
            kind=self.integration.kind, result="failed", reason=reason, attempt=attempt
        ).inc()
        self.integration.save()

    def _on_token_refreshed(self) -> None:
        logger.info(f"Refreshed access token for {self}")
        self.integration.errors = ""
        refresh_tracking.record_refresh_success(self.integration)
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
        refresh_tracking.oauth_refresh_counter.labels(
            kind=self.integration.kind, result="success", reason="", attempt=""
        ).inc()

    @database_sync_to_async
    def list_cached_repositories_async(
        self, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[dict], bool]:
        return self.list_cached_repositories(search=search, limit=limit, offset=offset)

    def create_issue(self, config: dict[str, Any]):
        title: str = config.pop("title")
        body: str = config.pop("body")
        repository: str = config.pop("repository")
        labels = config.pop("labels", None)

        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        json_body: dict[str, Any] = {"title": title, "body": body}
        if labels:
            json_body["labels"] = labels

        response = self.api_request(
            "POST",
            f"/repos/{repo_path}/issues",
            endpoint="/repos/{owner}/{repo}/issues",
            json_body=json_body,
        )
        if response.status_code != 201:
            raise GitHubIntegrationError(
                f"GitHubIntegration: failed to create issue in {repo_path}: {response.text[:300]}",
                status_code=response.status_code,
            )
        issue = response.json()

        return {"number": issue["number"], "repository": repository}

    def search_issues(self, repository: str, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Search existing GitHub issues in a repository for the link-existing flow."""
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        if not _is_safe_github_repo_path(repo_path):
            raise GitHubIntegrationError(f"GitHubIntegration: invalid repository path {repo_path!r}")

        # `repository` is stored bare in external_context so build_external_issue_url can re-prefix
        # the org, matching what create_issue persists.
        repository_name = repo_path.split("/", 1)[1]

        # Quote the user's text so search syntax in it (qualifiers like repo:, operators like OR)
        # is matched literally instead of rewriting the query, which would fill the result page
        # with foreign matches and hide valid ones.
        search_term = query.replace("\\", " ").replace('"', " ").strip()
        q = f'repo:{repo_path} "{search_term}" in:title type:issue' if search_term else f"repo:{repo_path} type:issue"

        response = self.api_request(
            "GET",
            "/search/issues",
            endpoint="/search/issues",
            params={"q": q, "per_page": limit},
        )
        if response.status_code != 200:
            raise GitHubIntegrationError(
                f"GitHubIntegration: failed to search issues in {repo_path}: {response.text[:300]}",
                status_code=response.status_code,
            )

        results: list[dict[str, Any]] = []
        for issue in response.json().get("items", []) or []:
            number = issue.get("number")
            if number is None:
                continue
            # The issues search API returns pull requests too; those aren't linkable issues.
            if issue.get("pull_request"):
                continue
            # Search-syntax operators in the user's query (e.g. "foo OR bar") can escape the
            # repo: qualifier, so drop anything that isn't actually from the chosen repository.
            repository_url = issue.get("repository_url") or ""
            if not repository_url.lower().endswith(f"/repos/{repo_path.lower()}"):
                continue
            results.append(
                {
                    "id": str(number),
                    "title": issue.get("title") or f"#{number}",
                    "url": issue.get("html_url") or "",
                    # Matches the shape GitHubIntegration.create_issue stores.
                    "external_context": {"repository": repository_name, "number": number},
                }
            )
        return results

    def create_branch(self, repository: str, branch_name: str, base_branch: str | None = None) -> dict[str, Any]:
        """Create a new branch from a base branch."""
        org = self.organization()

        # Get the SHA of the base branch (default to repository's default branch)
        if not base_branch:
            base_branch = self.get_default_branch(repository)

        # Get the SHA of the base branch
        ref_response = self.api_request(
            "GET",
            f"/repos/{org}/{repository}/git/ref/heads/{base_branch}",
            endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
        )

        if ref_response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to get base branch {base_branch}: {ref_response.text}",
            }

        base_sha = ref_response.json()["object"]["sha"]

        # Create the new branch
        response = self.api_request(
            "POST",
            f"/repos/{org}/{repository}/git/refs",
            endpoint="/repos/{owner}/{repo}/git/refs",
            json_body={
                "ref": f"refs/heads/{branch_name}",
                "sha": base_sha,
            },
        )

        if response.status_code == 201:
            branch_data = response.json()
            return {
                "success": True,
                "branch_name": branch_name,
                "sha": branch_data["object"]["sha"],
                "ref": branch_data["ref"],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to create branch: {response.text}",
                "status_code": response.status_code,
            }

    def commit_files_to_branch(
        self,
        repository: str,
        branch_name: str,
        base_branch: str,
        files: Mapping[str, str],
        commit_message: str,
        replace_directory: str | None = None,
    ) -> dict[str, Any]:
        """Point ``branch_name`` at a single commit on top of ``base_branch`` writing every file in
        ``files`` (repo-relative path → text content).

        Prefer this over ``create_branch`` plus one ``update_file`` per file when the files only make
        sense together: the commit object is built before the branch reference exists, so a failure
        part way through leaves nothing in the repository, and reviewers get one commit rather than
        one per file. An existing branch is force-updated to the new commit, discarding whatever was
        on it — callers republishing generated content want exactly that, callers collaborating on a
        branch do not.

        ``replace_directory`` makes the commit *replace* that directory with exactly the files given
        under it, instead of merging them into whatever ``base_branch`` already holds there. Without
        it a path that existed on the base and is absent from ``files`` survives, because the tree is
        built on the base tree: a caller republishing a generated directory would keep shipping files
        it has since deleted or renamed. Files outside the directory are still merged as usual.
        """
        if not files:
            return {"success": False, "error": "No files to commit"}

        org = self.organization()

        base_ref_response = self.api_request(
            "GET",
            f"/repos/{org}/{repository}/git/ref/heads/{base_branch}",
            endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
        )
        if base_ref_response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to get base branch {base_branch}: {base_ref_response.text}",
                "status_code": base_ref_response.status_code,
            }
        base_sha = base_ref_response.json()["object"]["sha"]

        base_commit_response = self.api_request(
            "GET",
            f"/repos/{org}/{repository}/git/commits/{base_sha}",
            endpoint="/repos/{owner}/{repo}/git/commits/{commit_sha}",
        )
        if base_commit_response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to read base commit {base_sha}: {base_commit_response.text}",
                "status_code": base_commit_response.status_code,
            }
        base_tree_sha = base_commit_response.json()["tree"]["sha"]

        # Inline `content` lets GitHub create the blobs as part of the tree, so no separate blob
        # round trip per file. 100644 is a non-executable file.
        def blob_entries(paths: Mapping[str, str]) -> list[dict[str, str]]:
            return [
                {"path": path, "mode": "100644", "type": "blob", "content": content} for path, content in paths.items()
            ]

        entries: list[dict[str, str]] = []
        if replace_directory:
            prefix = replace_directory.rstrip("/") + "/"
            inside = {path[len(prefix) :]: content for path, content in files.items() if path.startswith(prefix)}
            # Built with no base_tree, so this tree holds the given files and nothing else. Pointing
            # the directory entry at it swaps the whole subtree in one step, which is what makes a
            # path the caller dropped disappear rather than survive from the base tree.
            subtree_response = self.api_request(
                "POST",
                f"/repos/{org}/{repository}/git/trees",
                endpoint="/repos/{owner}/{repo}/git/trees",
                json_body={"tree": blob_entries(inside)},
            )
            if subtree_response.status_code != 201:
                return {
                    "success": False,
                    "error": f"Failed to create tree for {replace_directory}: {subtree_response.text}",
                    "status_code": subtree_response.status_code,
                }
            entries.append(
                {
                    "path": replace_directory.rstrip("/"),
                    "mode": "040000",
                    "type": "tree",
                    "sha": subtree_response.json()["sha"],
                }
            )
            entries.extend(blob_entries({p: c for p, c in files.items() if not p.startswith(prefix)}))
        else:
            entries = blob_entries(files)

        tree_response = self.api_request(
            "POST",
            f"/repos/{org}/{repository}/git/trees",
            endpoint="/repos/{owner}/{repo}/git/trees",
            json_body={"base_tree": base_tree_sha, "tree": entries},
        )
        if tree_response.status_code != 201:
            return {
                "success": False,
                "error": f"Failed to create tree: {tree_response.text}",
                "status_code": tree_response.status_code,
            }

        commit_response = self.api_request(
            "POST",
            f"/repos/{org}/{repository}/git/commits",
            endpoint="/repos/{owner}/{repo}/git/commits",
            json_body={
                "message": commit_message,
                "tree": tree_response.json()["sha"],
                "parents": [base_sha],
            },
        )
        if commit_response.status_code != 201:
            return {
                "success": False,
                "error": f"Failed to create commit: {commit_response.text}",
                "status_code": commit_response.status_code,
            }
        commit_sha = commit_response.json()["sha"]

        create_ref_response = self.api_request(
            "POST",
            f"/repos/{org}/{repository}/git/refs",
            endpoint="/repos/{owner}/{repo}/git/refs",
            json_body={"ref": f"refs/heads/{branch_name}", "sha": commit_sha},
        )
        if create_ref_response.status_code == 201:
            return {"success": True, "branch_name": branch_name, "commit_sha": commit_sha, "created_branch": True}

        # 422 is what GitHub returns for a reference that already exists; move it instead.
        if create_ref_response.status_code != 422:
            return {
                "success": False,
                "error": f"Failed to create branch {branch_name}: {create_ref_response.text}",
                "status_code": create_ref_response.status_code,
            }

        update_ref_response = self.api_request(
            "PATCH",
            f"/repos/{org}/{repository}/git/refs/heads/{branch_name}",
            endpoint="/repos/{owner}/{repo}/git/refs/heads/{branch}",
            json_body={"sha": commit_sha, "force": True},
        )
        if update_ref_response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to update branch {branch_name}: {update_ref_response.text}",
                "status_code": update_ref_response.status_code,
            }
        return {"success": True, "branch_name": branch_name, "commit_sha": commit_sha, "created_branch": False}

    def delete_branch(self, repository: str, branch_name: str, expected_sha: str | None = None) -> dict[str, Any]:
        """Delete a branch reference. A branch that is already gone counts as success.

        ``expected_sha`` makes the delete conditional: the ref is read first and left alone when it
        has moved on, which is what a caller cleaning up its own failed write wants on a branch name
        that is shared by construction. GitHub has no conditional delete, so this narrows the race
        rather than closing it.
        """
        org = self.organization()

        if expected_sha is not None:
            head_response = self.api_request(
                "GET",
                f"/repos/{org}/{repository}/git/ref/heads/{branch_name}",
                endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
            )
            if head_response.status_code == 404:
                return {"success": True, "branch_name": branch_name}
            if head_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to read branch {branch_name}: {head_response.text}",
                    "status_code": head_response.status_code,
                }
            if head_response.json()["object"]["sha"] != expected_sha:
                return {"success": True, "branch_name": branch_name, "skipped": True}

        response = self.api_request(
            "DELETE",
            f"/repos/{org}/{repository}/git/refs/heads/{branch_name}",
            endpoint="/repos/{owner}/{repo}/git/refs/heads/{branch}",
        )
        if response.status_code in (204, 404):
            return {"success": True, "branch_name": branch_name}
        # GitHub answers a delete with 422 both for a reference that is already gone and for one it
        # refused to remove, so the status alone can't tell "done" from "still there". Read the ref
        # back: absent is the success the caller wanted, present is a branch it has to hear about.
        if response.status_code == 422:
            recheck_response = self.api_request(
                "GET",
                f"/repos/{org}/{repository}/git/ref/heads/{branch_name}",
                endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
            )
            if recheck_response.status_code == 404:
                return {"success": True, "branch_name": branch_name}
        return {
            "success": False,
            "error": f"Failed to delete branch {branch_name}: {response.text}",
            "status_code": response.status_code,
        }

    def get_diff(
        self,
        repository: str,
        target_branch: str,
        base_branch: str,
        target_sha: str | None = None,
        base_sha: str | None = None,
    ) -> dict[str, Any]:
        """Return the unified diff of one branch/commit against another for ``repository``.

        ``repository`` may be ``owner/name`` or a bare name (resolved against the installation's
        org). The diff is ``base...target``: ``target_branch`` compared against ``base_branch``.
        A SHA, when supplied, pins that side to an exact commit; otherwise the side tracks the
        branch tip (``None`` means "use latest"). The branch is what's used when no SHA pins the
        point — diffing branch tips keeps the result useful as a branch keeps moving (e.g. after PR
        babysitting or customer tweaks), which a single pinned commit would not.

        Uses the GitHub compare API with the ``diff`` media type, so the response body is raw
        unified-diff text. Repository / ref / SHA values come from team-writable artefact content,
        so they're validated before interpolation — a crafted value could otherwise redirect the
        authenticated request to a different GitHub endpoint.
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        if not _is_safe_github_repo_path(repo_path):
            return {"success": False, "error": f"Invalid repository '{repository}'.", "status_code": 400}
        for ref in (target_branch, base_branch):
            if not _is_safe_github_ref(ref):
                return {"success": False, "error": f"Invalid branch '{ref}'.", "status_code": 400}
        for sha in (target_sha, base_sha):
            if sha is not None and not _is_safe_github_sha(sha):
                return {"success": False, "error": f"Invalid commit SHA '{sha}'.", "status_code": 400}

        # Pin to the SHA when we have one, else compare branch tips. Both sides are now built from
        # validated values, so the compare path can't be steered off-endpoint.
        base_ref = base_sha or base_branch
        target_ref = target_sha or target_branch

        try:
            response = self.api_request(
                "GET",
                f"/repos/{repo_path}/compare/{base_ref}...{target_ref}",
                endpoint="/repos/{owner}/{repo}/compare/{basehead}",
                headers={"Accept": "application/vnd.github.diff"},
            )
        except GitHubIntegrationError:
            # Don't let a slow/unreachable GitHub hang a worker or 500 the caller.
            return {"success": False, "error": "Could not reach GitHub.", "status_code": 502}
        if response.status_code != 200:
            return {"success": False, "error": response.text, "status_code": response.status_code}
        # Cap the diff we return: a branch touching generated/vendored files can produce a diff of
        # many MB, which would bloat the JSON response and worker memory. Truncate with a marker so
        # the consumer can tell the diff was cut rather than silently showing a partial diff.
        diff_text = response.text
        truncated = len(diff_text) > _MAX_DIFF_CHARS
        if truncated:
            diff_text = diff_text[:_MAX_DIFF_CHARS] + "\n\n… diff truncated (too large to display in full) …\n"
        return {"success": True, "diff": diff_text, "truncated": truncated}

    def update_file(
        self, repository: str, file_path: str, content: str, commit_message: str, branch: str, sha: str | None = None
    ) -> dict[str, Any]:
        """Create or update a file in the repository."""
        org = self.organization()

        # If no SHA provided, try to get existing file's SHA
        if not sha:
            get_response = self.api_request(
                "GET",
                f"/repos/{org}/{repository}/contents/{file_path}",
                endpoint="/repos/{owner}/{repo}/contents/{path}",
                params={"ref": branch},
            )
            if get_response.status_code == 200:
                sha = get_response.json()["sha"]

        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        data = {
            "message": commit_message,
            "content": encoded_content,
            "branch": branch,
        }

        if sha:
            data["sha"] = sha

        response = self.api_request(
            "PUT",
            f"/repos/{org}/{repository}/contents/{file_path}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            json_body=data,
        )

        if response.status_code in [200, 201]:
            commit_data = response.json()
            return {
                "success": True,
                "commit_sha": commit_data["commit"]["sha"],
                "file_sha": commit_data["content"]["sha"],
                "html_url": commit_data["commit"]["html_url"],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to update file: {response.text}",
                "status_code": response.status_code,
            }

    def get_file_contents(self, repository: str, file_path: str, ref: str | None = None) -> dict[str, Any] | None:
        """Read a file's decoded text and blob SHA at ``ref`` (default branch when omitted).

        Returns ``{"content": str, "sha": str}``, or ``None`` when the file does not
        exist — a missing file is a normal state, not an error. The SHA lets a caller
        pass it straight to ``update_file`` for a conflict-safe write. Counterpart to
        ``update_file``, kept here so URL and token handling stay inside the client.
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        response = self.api_request(
            "GET",
            f"/repos/{repo_path}/contents/{file_path}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref} if ref else None,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitHubIntegrationError(
                f"Failed to read {file_path} from {repository}: {response.text}",
                status_code=response.status_code,
            )
        payload = response.json()
        return {"content": base64.b64decode(payload["content"]).decode("utf-8"), "sha": payload["sha"]}

    def create_pull_request(
        self, repository: str, title: str, body: str, head_branch: str, base_branch: str | None = None
    ) -> dict[str, Any]:
        """Create a pull request."""
        org = self.organization()

        if not base_branch:
            base_branch = self.get_default_branch(repository)

        response = self.api_request(
            "POST",
            f"/repos/{org}/{repository}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            json_body={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch,
            },
        )

        if response.status_code == 201:
            pr_data = response.json()
            return {
                "success": True,
                "pr_number": pr_data["number"],
                "pr_url": pr_data["html_url"],
                "pr_id": pr_data["id"],
                "state": pr_data["state"],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to create pull request: {response.text}",
                "status_code": response.status_code,
            }

    def get_branch_info(self, repository: str, branch_name: str) -> dict[str, Any]:
        """Get information about a specific branch."""
        org = self.organization()

        response = self.api_request(
            "GET",
            f"/repos/{org}/{repository}/branches/{branch_name}",
            endpoint="/repos/{owner}/{repo}/branches/{branch}",
        )

        if response.status_code == 200:
            branch_data = response.json()
            return {
                "success": True,
                "exists": True,
                "branch_name": branch_data["name"],
                "commit_sha": branch_data["commit"]["sha"],
                "protected": branch_data.get("protected", False),
            }
        elif response.status_code == 404:
            return {
                "success": True,
                "exists": False,
                "branch_name": branch_name,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to get branch info: {response.text}",
                "status_code": response.status_code,
            }

    def list_pull_requests(self, repository: str, state: str = "open") -> dict[str, Any]:
        """List pull requests for a repository."""
        org = self.organization()

        params: dict[str, str | int] = {"state": state, "per_page": 100}
        response = self.api_request(
            "GET",
            f"/repos/{org}/{repository}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params=params,
        )

        if response.status_code == 200:
            prs = response.json()
            return {
                "success": True,
                "pull_requests": [
                    {
                        "number": pr["number"],
                        "title": pr["title"],
                        "url": pr["html_url"],
                        "state": pr["state"],
                        "head_branch": pr["head"]["ref"],
                        "base_branch": pr["base"]["ref"],
                        "created_at": pr["created_at"],
                        "updated_at": pr["updated_at"],
                    }
                    for pr in prs
                ],
            }
        else:
            return {
                "success": False,
                "error": f"Failed to list pull requests: {response.text}",
                "status_code": response.status_code,
            }
