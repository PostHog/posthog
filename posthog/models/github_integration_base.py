"""Base class for GitHub integrations (team-scoped and user-scoped).

Provides installation-token management and installation-authenticated GitHub API
operations that are shared between :class:`GitHubIntegration` (team-scoped) and
:class:`UserGitHubIntegration` (user-scoped).
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import jwt
import requests
import structlog
from prometheus_client import Counter, Gauge

logger = structlog.get_logger(__name__)

github_api_request_counter = Counter(
    "github_integration_api_requests",
    "Number of GitHub API requests made through a GitHub integration.",
    labelnames=["integration_id", "method", "endpoint", "status_code"],
)
github_api_rate_limit_remaining_gauge = Gauge(
    "github_integration_api_rate_limit_remaining",
    "Most recently observed GitHub API rate limit remaining count by integration and resource.",
    labelnames=["integration_id", "resource"],
)
github_api_rate_limit_limit_gauge = Gauge(
    "github_integration_api_rate_limit_limit",
    "Most recently observed GitHub API rate limit limit by integration and resource.",
    labelnames=["integration_id", "resource"],
)
github_api_rate_limit_reset_timestamp_gauge = Gauge(
    "github_integration_api_rate_limit_reset_timestamp_seconds",
    "Most recently observed GitHub API rate limit reset timestamp by integration and resource.",
    labelnames=["integration_id", "resource"],
)
github_cache_access_counter = Counter(
    "github_integration_cache_accesses",
    "Number of GitHub integration cache accesses by cache type, repository, and result.",
    labelnames=["integration_id", "cache", "repository", "result"],
)

# Repository cache: 1-hour staleness window.
GITHUB_REPOSITORY_CACHE_TTL_SECONDS = 60 * 60

# Branch cache: 10-minute staleness, 24-hour eviction timeout.
GITHUB_BRANCH_CACHE_TTL_SECONDS = 60 * 10
GITHUB_BRANCH_CACHE_TIMEOUT_SECONDS = 60 * 60 * 24


@dataclass(frozen=True)
class GitHubCommitAuthor:
    login: str
    name: str | None
    commit_url: str


class GitHubIntegrationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_rate_limit: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        # Needed, so retry wrappers can make decisions without reparsing the response.
        self.status_code = status_code
        self.is_rate_limit = is_rate_limit
        self.retry_after_seconds = retry_after_seconds


class GitHubIntegrationBase:
    """Installation-token operations shared between team and user GitHub integrations."""

    integration: Any  # Integration | UserIntegration -- subclasses narrow the type

    @property
    def github_installation_id(self) -> str | None:
        """The GitHub App installation ID. Override in subclasses where the field name differs."""
        return self.integration.integration_id

    # --- App-level JWT authentication ---

    @classmethod
    def client_request(cls, endpoint: str, method: str = "GET") -> requests.Response:
        """Make a request to the GitHub App API using a JWT."""
        from rest_framework.exceptions import ValidationError

        github_app_client_id = settings.GITHUB_APP_CLIENT_ID
        github_app_private_key = settings.GITHUB_APP_PRIVATE_KEY

        if not github_app_client_id:
            raise ValidationError("GITHUB_APP_CLIENT_ID is not configured")
        if not github_app_private_key:
            raise ValidationError("GITHUB_APP_PRIVATE_KEY is not configured")

        github_app_private_key = github_app_private_key.replace("\\n", "\n").strip()

        try:
            jwt_token = jwt.encode(
                {
                    "iat": int(time.time()) - 300,
                    "exp": int(time.time()) + 300,
                    "iss": github_app_client_id,
                },
                github_app_private_key,
                algorithm="RS256",
            )
        except Exception:
            logger.error("Failed to encode JWT token", exc_info=True)
            raise ValidationError(
                "Failed to create GitHub App JWT token. Please check your GITHUB_APP_PRIVATE_KEY format."
            )

        return requests.request(
            method,
            f"https://api.github.com/app/{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @staticmethod
    def verify_user_installation_access(installation_id: str, user_access_token: str) -> bool:
        """Check that a GitHub user has access to the given App installation.

        Calls ``GET /user/installations/{id}/repositories`` with the user's
        OAuth token.  Returns ``True`` when the user has access, ``False``
        when GitHub returns 404 (no access).  Raises on network errors or
        unexpected status codes so callers can surface an appropriate error.
        """
        response = requests.get(  # nosemgrep: python.django.security.injection.ssrf.ssrf-injection-requests.ssrf-injection-requests -- installation_id is validated as digits-only by callers
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {user_access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"per_page": 1},
            timeout=10,
        )
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        logger.warning(
            "verify_user_installation_access: unexpected status",
            installation_id=installation_id,
            status_code=response.status_code,
        )
        raise requests.RequestException(f"Unexpected status {response.status_code} verifying installation access")

    @staticmethod
    def _rate_limit_header(headers: Mapping[str, str] | None, name: str) -> float | None:
        if headers is None:
            return None
        value = headers.get(name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _record_github_api_response(self, response: requests.Response, method: str, endpoint: str) -> None:
        integration_id = str(self.integration.id)
        status_code = str(response.status_code)
        github_api_request_counter.labels(integration_id, method, endpoint, status_code).inc()

        headers = response.headers if isinstance(response.headers, Mapping) else None
        resource = headers.get("X-RateLimit-Resource", "unknown") if headers is not None else "unknown"
        remaining = self._rate_limit_header(headers, "X-RateLimit-Remaining")
        limit = self._rate_limit_header(headers, "X-RateLimit-Limit")
        reset_at = self._rate_limit_header(headers, "X-RateLimit-Reset")

        if remaining is not None:
            github_api_rate_limit_remaining_gauge.labels(integration_id, resource).set(remaining)
        if limit is not None:
            github_api_rate_limit_limit_gauge.labels(integration_id, resource).set(limit)
        if reset_at is not None:
            github_api_rate_limit_reset_timestamp_gauge.labels(integration_id, resource).set(reset_at)

    def _record_github_api_exception(self, method: str, endpoint: str) -> None:
        github_api_request_counter.labels(str(self.integration.id), method, endpoint, "exception").inc()

    def _record_github_cache_access(
        self, cache_type: Literal["repositories", "branches"], result: Literal["hit", "miss"], repository: str
    ) -> None:
        github_cache_access_counter.labels(str(self.integration.id), cache_type, repository.casefold(), result).inc()

    def _github_api_get(
        self,
        url: str,
        *,
        endpoint: str,
        headers: dict[str, str],
        params: dict[str, str | int] | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        except requests.RequestException:
            self._record_github_api_exception("GET", endpoint)
            raise
        self._record_github_api_response(response, "GET", endpoint)
        return response

    def _github_api_post(
        self,
        url: str,
        *,
        endpoint: str,
        headers: dict[str, str],
        json_body: Mapping[str, object] | None = None,
    ) -> requests.Response:
        try:
            response = requests.post(url, json=json_body, headers=headers)
        except requests.RequestException:
            self._record_github_api_exception("POST", endpoint)
            raise
        self._record_github_api_response(response, "POST", endpoint)
        return response

    def _github_api_put(
        self,
        url: str,
        *,
        endpoint: str,
        headers: dict[str, str],
        json_body: Mapping[str, object],
    ) -> requests.Response:
        try:
            response = requests.put(url, json=json_body, headers=headers)
        except requests.RequestException:
            self._record_github_api_exception("PUT", endpoint)
            raise
        self._record_github_api_response(response, "PUT", endpoint)
        return response

    # --- Installation access token ---

    @property
    def installation_access_token(self) -> str | None:
        sc = self.integration.sensitive_config
        return sc.get("access_token") if sc else None

    def access_token_expired(self) -> bool:
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not expires_in or not refreshed_at:
            return False
        threshold = max(1, int(expires_in / 2))
        return time.time() > refreshed_at + expires_in - threshold

    def refresh_access_token(self) -> None:
        """Refresh the installation access token via the GitHub App JWT.

        Calls :meth:`_on_token_refresh_failed` or :meth:`_on_token_refreshed`
        so subclasses can add side effects (error recording, counters, worker
        reloads).

        On failure the hook is called and then an exception is raised; the hook
        is responsible for persisting any error state it needs.  On success the
        hook is called *before* ``save()`` so it can mutate extra fields that
        will be included in a single write.
        """
        endpoint = "/app/installations/{installation_id}/access_tokens"
        try:
            response = self.client_request(f"installations/{self.github_installation_id}/access_tokens", method="POST")
        except requests.RequestException:
            self._record_github_api_exception("POST", endpoint)
            raise
        self._record_github_api_response(response, "POST", endpoint)
        try:
            data = response.json()
        except ValueError:
            self._on_token_refresh_failed(response)
            raise Exception(f"Non-JSON response when refreshing installation token: {response.text[:500]}") from None

        if response.status_code != 201 or not data.get("token"):
            self._on_token_refresh_failed(response)
            raise Exception(f"Failed to refresh installation token: {response.text}")

        if "expires_at" not in data:
            raise Exception("GitHub API response missing expires_at field")
        try:
            expires_in = datetime.fromisoformat(data["expires_at"]).timestamp() - int(time.time())
        except ValueError as e:
            raise Exception(f"Invalid expires_at format from GitHub: {e}")

        self.integration.config = {
            **self.integration.config,
            "expires_in": expires_in,
            "refreshed_at": int(time.time()),
        }
        self.integration.sensitive_config = {
            **(self.integration.sensitive_config or {}),
            "access_token": data["token"],
        }
        self._on_token_refreshed()
        self.integration.save()

    def _on_token_refresh_failed(self, response: requests.Response) -> None:
        """Called when the installation token refresh request fails.

        Override to persist error state, increment counters, etc.  The base
        implementation only logs.
        """
        logger.warning(
            "GitHubIntegration: installation token refresh failed",
            integration_id=self.integration.id,
            status_code=response.status_code,
        )

    def _on_token_refreshed(self) -> None:
        """Called after a successful token refresh, before ``save()``.

        Override to clear errors, notify workers, increment counters, etc.
        Mutations to ``self.integration`` will be included in the same save.
        """
        logger.info(
            "GitHubIntegration: refreshed installation access token",
            integration_id=self.integration.id,
        )

    # --- Authenticated API helpers ---

    def _installation_authenticated_get(
        self, url: str, *, endpoint: str, timeout: int = 10
    ) -> requests.Response | None:
        """GET with installation token; refreshes on expiry or 401."""
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch() -> requests.Response:
            access_token = (self.integration.sensitive_config or {}).get("access_token")
            return self._github_api_get(
                url,
                endpoint=endpoint,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=timeout,
            )

        try:
            response = fetch()
            if response.status_code == 401:
                try:
                    self.refresh_access_token()
                except Exception:
                    logger.warning("GitHubIntegration: token refresh after 401 failed", exc_info=True)
                    return None
                response = fetch()
            return response
        except Exception:
            logger.warning("GitHubIntegration: installation GET failed", url=url, exc_info=True)
            return None

    def installation_can_access_repository(self, repository: str) -> bool:
        """Whether this installation token can access the repo (``GET /repos/{owner}/{repo}`` returns 200)."""
        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repository}", endpoint="/repos/{owner}/{repo}"
        )
        if response is None:
            return False
        return response.status_code == 200

    def organization(self) -> str:
        name = self.integration.config.get("account", {}).get("name")
        if not isinstance(name, str):
            raise ValueError(f"GitHub integration account name is not a string: {name}")
        return name

    # --- Repository operations ---

    def get_commit_author_info(self, repository: str, sha: str) -> GitHubCommitAuthor | None:
        """Resolve a commit SHA to author metadata via the GitHub API."""
        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repository}/commits/{sha}",
            endpoint="/repos/{owner}/{repo}/commits/{sha}",
        )
        if response is None:
            return None
        if response.status_code != 200:
            logger.info(
                "GitHub API non-200 for commit lookup",
                status_code=response.status_code,
                sha_prefix=sha[:8],
                repository=repository,
            )
            return None
        try:
            data = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: failed to parse commit JSON",
                repository=repository,
                sha_prefix=sha[:8],
                exc_info=True,
            )
            return None
        author = data.get("author")
        if not author or not author.get("login"):
            return None
        git_author = data.get("commit", {}).get("author", {})
        name = git_author.get("name") or author.get("login")
        commit_url = data.get("html_url", f"https://github.com/{repository}/commit/{sha}")
        return GitHubCommitAuthor(login=author["login"], name=name, commit_url=commit_url)

    @staticmethod
    def parse_pull_request_url(pr_url: str) -> tuple[str, str, int] | None:
        """Parse a GitHub pull request URL into ``(owner, repo, pr_number)``.

        Returns ``None`` if the URL does not look like a GitHub PR URL.
        """
        try:
            parsed = urlparse(pr_url)
        except Exception:
            return None
        if parsed.netloc not in {"github.com", "www.github.com"}:
            return None
        parts = [p for p in parsed.path.split("/") if p]
        # Expected path: /{owner}/{repo}/pull/{number}[/...]
        if len(parts) < 4 or parts[2] != "pull":
            return None
        owner, repo, _, pr_number_str = parts[:4]
        try:
            pr_number = int(pr_number_str)
        except ValueError:
            return None
        return owner, repo, pr_number

    def get_pull_request(self, repository: str, pr_number: int) -> dict[str, Any]:
        """Fetch a pull request by repository (``owner/repo`` or just ``repo``) and PR number."""
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repo_path}/pulls/{pr_number}",
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
        )
        if response is None:
            return {"success": False, "error": "Network error fetching pull request"}
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to fetch pull request: {response.text}",
                "status_code": response.status_code,
            }
        try:
            pr = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: get_pull_request non-JSON response",
                repository=repo_path,
                pr_number=pr_number,
            )
            return {"success": False, "error": "Failed to parse pull request JSON"}

        head = pr.get("head") or {}
        base = pr.get("base") or {}
        user = pr.get("user") or {}

        return {
            "success": True,
            "number": pr.get("number"),
            "title": pr.get("title"),
            "body": pr.get("body"),
            "url": pr.get("html_url"),
            "state": pr.get("state"),
            "merged": pr.get("merged", False),
            "draft": pr.get("draft", False),
            "head_branch": head.get("ref"),
            "base_branch": base.get("ref"),
            "head_sha": head.get("sha"),
            "base_sha": base.get("sha"),
            "repository": repo_path,
            "author": user.get("login"),
            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "merged_at": pr.get("merged_at"),
            "closed_at": pr.get("closed_at"),
            "comments": pr.get("comments", 0),
            "review_comments": pr.get("review_comments", 0),
            "commits": pr.get("commits", 0),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed_files": pr.get("changed_files", 0),
        }

    def get_pull_request_from_url(self, pr_url: str) -> dict[str, Any]:
        """Fetch a pull request by its HTML URL (e.g. ``https://github.com/owner/repo/pull/123``)."""
        parsed = self.parse_pull_request_url(pr_url)
        if parsed is None:
            return {"success": False, "error": f"Invalid GitHub pull request URL: {pr_url}"}
        owner, repo, pr_number = parsed
        return self.get_pull_request(f"{owner}/{repo}", pr_number)

    def list_repositories(self, *, page: int = 1, per_page: int = 100) -> tuple[list[dict], bool]:
        """List one page of installation repositories from the GitHub API.

        Uses GitHub's ``page`` and ``per_page`` query parameters
        (``per_page`` is clamped to 1–100, the API maximum). Returns
        ``(repositories, has_more)`` where *has_more* is true when the page is
        full, so another page may exist.
        """
        page = max(1, page)
        per_page = max(1, min(100, per_page))

        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch() -> requests.Response:
            access_token = (self.integration.sensitive_config or {}).get("access_token")
            return self._github_api_get(
                f"https://api.github.com/installation/repositories?page={page}&per_page={per_page}",
                endpoint="/installation/repositories",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        def extract_repos(body: dict) -> list[dict]:
            repositories = body.get("repositories")
            if not isinstance(repositories, list):
                logger.warning(
                    "GitHubIntegration: list_repositories invalid payload",
                    integration_id=self.integration.id,
                    payload_keys=sorted(body.keys()),
                )
                raise GitHubIntegrationError("GitHubIntegration: list_repositories invalid payload")
            return [
                {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                }
                for repo in repositories
                if isinstance(repo, dict)
                and isinstance(repo.get("id"), int)
                and isinstance(repo.get("name"), str)
                and isinstance(repo.get("full_name"), str)
            ]

        def raise_repository_error(message: str, *, status_code: int | None = None, exc_info: bool = False) -> None:
            logger.warning(
                message,
                integration_id=self.integration.id,
                status_code=status_code,
                exc_info=exc_info,
            )
            raise GitHubIntegrationError(message)

        transient_status_codes = {502, 503, 504}

        for attempt in range(2):
            try:
                response = fetch()
            except requests.RequestException:
                raise_repository_error("GitHubIntegration: list_repositories network error", exc_info=True)

            if response.status_code == 401:
                try:
                    self.refresh_access_token()
                except Exception:
                    raise_repository_error("GitHubIntegration: token refresh after 401 failed", exc_info=True)
                try:
                    response = fetch()
                except requests.RequestException:
                    raise_repository_error("GitHubIntegration: list_repositories network error on retry", exc_info=True)

            try:
                body = response.json()
            except Exception:
                if response.status_code in transient_status_codes and attempt == 0:
                    logger.info(
                        "GitHubIntegration: list_repositories retrying transient non-JSON response",
                        status_code=response.status_code,
                    )
                    continue
                logger.warning(
                    "GitHubIntegration: list_repositories non-JSON response",
                    integration_id=self.integration.id,
                    status_code=response.status_code,
                )
                raise GitHubIntegrationError("GitHubIntegration: list_repositories non-JSON response")

            if response.status_code == 200 and isinstance(body, dict):
                page_repos = extract_repos(body)
                has_more = len(page_repos) == per_page
                return page_repos, has_more

            if response.status_code in transient_status_codes and attempt == 0:
                logger.info(
                    "GitHubIntegration: list_repositories retrying transient error",
                    status_code=response.status_code,
                    error=body if isinstance(body, dict) else None,
                )
                continue

            logger.warning(
                "GitHubIntegration: failed to list repositories",
                integration_id=self.integration.id,
                status_code=response.status_code,
                error=body if isinstance(body, dict) else None,
            )
            raise GitHubIntegrationError("GitHubIntegration: failed to list repositories")
        raise GitHubIntegrationError("GitHubIntegration: failed to list repositories after retries")

    def list_all_repositories(self) -> list[dict]:
        """Fetch all accessible repositories, paginating through GitHub's API."""
        all_repositories: list[dict] = []
        page = 1
        per_page = 100

        while True:
            repositories, has_more = self.list_repositories(page=page, per_page=per_page)
            all_repositories.extend(repositories)

            if not has_more or not repositories:
                return all_repositories

            page += 1

    def list_branches(self, repo: str, *, limit: int = 100, offset: int = 0) -> tuple[list[str], bool]:
        """List branches for a given repository via the GitHub API.

        Fetches only the GitHub pages needed to satisfy the requested
        ``[offset, offset+limit)`` window. Returns a tuple of
        ``(branch_names, has_more)`` where *has_more* indicates whether
        additional branches exist beyond the returned window.
        """
        GITHUB_PER_PAGE = 100

        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch(page: int) -> requests.Response:
            access_token = (self.integration.sensitive_config or {}).get("access_token")
            return self._github_api_get(
                f"https://api.github.com/repos/{repo}/branches?per_page={GITHUB_PER_PAGE}&page={page}",
                endpoint="/repos/{owner}/{repo}/branches",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )

        def extract_names(data: list) -> list[str]:
            return [
                branch["name"] for branch in data if isinstance(branch, dict) and isinstance(branch.get("name"), str)
            ]

        # Work out which GitHub pages cover the requested window.
        first_page = offset // GITHUB_PER_PAGE + 1
        skip = offset % GITHUB_PER_PAGE
        needed = skip + limit

        # Fetch the first required page (with 401-retry logic).
        current_page = first_page
        try:
            response = fetch(current_page)
        except requests.RequestException:
            logger.warning("GitHubIntegration: list_branches network error", repo=repo, exc_info=True)
            return [], False

        if response.status_code == 401:
            try:
                self.refresh_access_token()
            except Exception:
                logger.warning("GitHubIntegration: token refresh after 401 failed", exc_info=True)
                return [], False
            try:
                response = fetch(current_page)
            except requests.RequestException:
                logger.warning("GitHubIntegration: list_branches network error on retry", repo=repo, exc_info=True)
                return [], False

        if response.status_code != 200:
            logger.warning(
                "GitHubIntegration: failed to list branches",
                status_code=response.status_code,
                repo=repo,
            )
            return [], False

        try:
            body = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: list_branches non-JSON response",
                status_code=response.status_code,
            )
            return [], False

        if not isinstance(body, list):
            return [], False

        all_fetched = extract_names(body)
        has_next_page = 'rel="next"' in response.headers.get("Link", "")

        # Fetch subsequent pages until we have enough items.
        while len(all_fetched) < needed and has_next_page:
            current_page += 1
            try:
                response = fetch(current_page)
            except requests.RequestException:
                break
            if response.status_code != 200:
                logger.warning(
                    "GitHubIntegration.list_branches pagination stopped",
                    status_code=response.status_code,
                    page=current_page,
                    repo=repo,
                )
                break
            try:
                body = response.json()
            except Exception:
                break
            if not isinstance(body, list):
                break
            all_fetched.extend(extract_names(body))
            has_next_page = 'rel="next"' in response.headers.get("Link", "")

        result = all_fetched[skip : skip + limit]
        has_more = has_next_page or (skip + limit < len(all_fetched))

        return result, has_more

    def list_all_branches(self, repo: str) -> list[str]:
        """Fetch all branches for a repository, paginating through GitHub's API."""
        all_branches: list[str] = []
        offset = 0
        page_size = 100

        while True:
            branches, has_more = self.list_branches(repo, limit=page_size, offset=offset)
            all_branches.extend(branches)

            if not has_more or not branches:
                return all_branches

            offset += len(branches)

    def get_top_starred_repository(self) -> str | None:
        """Get the repository with the most stars from the GitHub integration.

        Returns the full repository name in format 'org/repo', or None if no repos available.
        """
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        def fetch(page: int = 1) -> requests.Response:
            access_token = (self.integration.sensitive_config or {}).get("access_token")
            return self._github_api_get(
                f"https://api.github.com/installation/repositories?page={page}&per_page=100",
                endpoint="/installation/repositories",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        response = fetch()

        if response.status_code == 401:
            try:
                self.refresh_access_token()
            except Exception:
                logger.warning("GitHubIntegration: token refresh after 401 failed", exc_info=True)
            else:
                response = fetch()

        try:
            body = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: get_top_starred_repository non-JSON response",
                status_code=response.status_code,
            )
            return None

        repositories = body.get("repositories")
        if response.status_code != 200 or not isinstance(repositories, list) or not repositories:
            return None

        top_repo = max(repositories, key=lambda r: r.get("stargazers_count", 0) if isinstance(r, dict) else 0)
        if not isinstance(top_repo, dict):
            return None

        full_name = top_repo.get("full_name")
        if isinstance(full_name, str):
            return full_name.lower()

        return None

    def get_default_branch(self, repository: str) -> str:
        """Get the default branch for a repository."""
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        cache_key = f"github_integration:default_branch:{self.integration.id}:{repo_path}"

        cached = cache.get(cache_key)
        if isinstance(cached, str):
            return cached

        access_token = (self.integration.sensitive_config or {}).get("access_token")
        if not access_token:
            raise ValueError("GitHub access token not configured")

        response = self._github_api_get(
            f"https://api.github.com/repos/{repo_path}",
            endpoint="/repos/{owner}/{repo}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )

        if response.status_code == 200:
            repo_data = response.json()
            default_branch = repo_data.get("default_branch", "main")
            cache.set(cache_key, default_branch, timeout=60 * 60 * 24)
            return default_branch
        else:
            raise Exception(f"Failed to get default branch: HTTP {response.status_code}")

    # --- Cached repository operations ---

    def _get_stored_repository_list(self) -> list[dict] | None:
        """Repositories persisted on the integration row."""
        cached = self.integration.repository_cache
        if not isinstance(cached, list):
            return None
        return [
            {
                "id": repo["id"],
                "name": repo["name"],
                "full_name": repo["full_name"],
            }
            for repo in cached
            if isinstance(repo, dict)
            and isinstance(repo.get("id"), int)
            and isinstance(repo.get("name"), str)
            and isinstance(repo.get("full_name"), str)
        ]

    def repository_cache_is_stale(self) -> bool:
        updated_at = self.integration.repository_cache_updated_at
        if updated_at is None:
            return True
        return (timezone.now() - updated_at).total_seconds() >= GITHUB_REPOSITORY_CACHE_TTL_SECONDS

    def sync_repository_cache(self, min_refresh_interval_seconds: int | None = None) -> list[dict]:
        cached_repositories = self._get_stored_repository_list()
        updated_at = self.integration.repository_cache_updated_at
        if (
            min_refresh_interval_seconds is not None
            and cached_repositories is not None
            and updated_at is not None
            and (timezone.now() - updated_at).total_seconds() < min_refresh_interval_seconds
        ):
            return cached_repositories

        repositories = self.list_all_repositories()
        refreshed_at = timezone.now()
        update_fields = ["repository_cache_updated_at"]
        if repositories != cached_repositories:
            self.integration.repository_cache = repositories
            update_fields.insert(0, "repository_cache")
        self.integration.repository_cache_updated_at = refreshed_at
        self.integration.save(update_fields=update_fields)
        return repositories

    def _filter_cached_repositories(self, repositories: list[dict], search: str) -> list[dict]:
        search_query = search.strip().casefold()
        if not search_query:
            return repositories
        return [
            repository for repository in repositories if search_query in str(repository.get("full_name", "")).casefold()
        ]

    def list_cached_repositories(
        self, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[dict], bool]:
        cached_repositories = self._get_stored_repository_list()
        has_cached_snapshot = self.integration.repository_cache_updated_at is not None
        should_refresh = cached_repositories is None or self.repository_cache_is_stale()
        self._record_github_cache_access("repositories", "miss" if should_refresh else "hit", "__all__")

        if should_refresh:
            try:
                cached_repositories = self.sync_repository_cache()
            except Exception:
                logger.warning(
                    "GitHubIntegration: failed to refresh repository cache",
                    integration_id=self.integration.id,
                    exc_info=True,
                )
                if not has_cached_snapshot:
                    raise

        if cached_repositories is None:
            cached_repositories = []

        filtered = self._filter_cached_repositories(cached_repositories, search)
        result = filtered[offset : offset + limit]
        has_more = offset + limit < len(filtered)
        return result, has_more

    def list_all_cached_repositories(self, max_repos: int | None = None) -> list[dict]:
        cached_repositories = self._get_stored_repository_list()
        has_cached_snapshot = self.integration.repository_cache_updated_at is not None
        should_refresh = cached_repositories is None or self.repository_cache_is_stale()
        self._record_github_cache_access("repositories", "miss" if should_refresh else "hit", "__all__")

        if should_refresh:
            try:
                cached_repositories = self.sync_repository_cache()
            except Exception:
                logger.warning(
                    "GitHubIntegration: failed to refresh repository cache",
                    integration_id=self.integration.id,
                    exc_info=True,
                )
                if not has_cached_snapshot:
                    raise

        if cached_repositories is None:
            cached_repositories = []

        if max_repos is not None:
            return cached_repositories[:max_repos]
        return cached_repositories

    # --- Cached branch operations ---

    def _get_branch_cache_key(self, repo: str) -> str:
        return f"github_integration:branches:{self.integration.id}:{repo.lower()}"

    def _get_branch_cache(self, repo: str) -> dict[str, Any] | None:
        cached = cache.get(self._get_branch_cache_key(repo))
        if not isinstance(cached, dict):
            return None

        branches = cached.get("branches")
        default_branch = cached.get("default_branch")
        updated_at = cached.get("updated_at")
        if not isinstance(branches, list) or not all(isinstance(branch, str) for branch in branches):
            return None
        if default_branch is not None and not isinstance(default_branch, str):
            return None
        if not isinstance(updated_at, (int, float)):
            return None

        return {
            "branches": branches,
            "default_branch": default_branch,
            "updated_at": updated_at,
        }

    def branch_cache_is_stale(self, repo: str) -> bool:
        cached = self._get_branch_cache(repo)
        if cached is None:
            return True
        return time.time() - float(cached["updated_at"]) >= GITHUB_BRANCH_CACHE_TTL_SECONDS

    def sync_branch_cache(self, repo: str) -> tuple[list[str], str | None]:
        branches = self.list_all_branches(repo)
        cached = self._get_branch_cache(repo)
        cached_default_branch = None if cached is None else cast(str | None, cached.get("default_branch"))

        default_branch: str | None
        try:
            default_branch = self.get_default_branch(repo)
        except Exception:
            logger.warning(
                "GitHubIntegration: failed to refresh default branch",
                integration_id=self.integration.id,
                repo=repo,
                exc_info=True,
            )
            default_branch = cached_default_branch if cached_default_branch in branches else None

        if default_branch and default_branch in branches:
            branches = [branch for branch in branches if branch != default_branch]
            branches.insert(0, default_branch)

        cache.set(
            self._get_branch_cache_key(repo),
            {
                "branches": branches,
                "default_branch": default_branch,
                "updated_at": time.time(),
            },
            timeout=GITHUB_BRANCH_CACHE_TIMEOUT_SECONDS,
        )

        return branches, default_branch

    def list_cached_branches(
        self, repo: str, *, search: str = "", limit: int = 100, offset: int = 0
    ) -> tuple[list[str], str | None, bool]:
        cached = self._get_branch_cache(repo)
        should_refresh = cached is None or self.branch_cache_is_stale(repo)
        self._record_github_cache_access("branches", "miss" if should_refresh else "hit", repo)

        if should_refresh:
            try:
                branches, default_branch = self.sync_branch_cache(repo)
                cached = {
                    "branches": branches,
                    "default_branch": default_branch,
                }
            except Exception:
                logger.warning(
                    "GitHubIntegration: failed to refresh branch cache",
                    integration_id=self.integration.id,
                    repo=repo,
                    exc_info=True,
                )
                if cached is None:
                    raise

        assert cached is not None
        branches = cast(list[str], cached["branches"])
        default_branch = cast(str | None, cached.get("default_branch"))

        normalized_search = search.strip().casefold()
        filtered_branches = (
            [branch for branch in branches if normalized_search in branch.casefold()] if normalized_search else branches
        )

        result = filtered_branches[offset : offset + limit]
        has_more = offset + limit < len(filtered_branches)
        return result, default_branch, has_more
