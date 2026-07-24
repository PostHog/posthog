"""Base class for GitHub integrations (team-scoped and user-scoped).

Provides installation-token management and installation-authenticated GitHub API
operations that are shared between :class:`GitHubIntegration` (team-scoped) and
:class:`UserGitHubIntegration` (user-scoped).
"""

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypedDict, cast
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import jwt
import requests
import structlog
from prometheus_client import Counter

from posthog.egress.github.limiter import remember_observed_core_limit
from posthog.egress.github.transport import GitHubRateLimitError, github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority
from posthog.sync import database_sync_to_async_pool

logger = structlog.get_logger(__name__)

# This client always knows its installation, so it records under source="integration" with a real id.
_OBSERVABILITY_SOURCE = "integration"

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

INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY = "installation_unavailable_since"


class NormalizedPRComment(TypedDict):
    """Wire shape for a PR comment shared by the read path and the review-comment write endpoints."""

    id: str
    author: str | None
    author_avatar_url: str | None
    body: str
    created_at: str | None
    url: str | None
    comment_type: str
    # Diff-anchor fields are only populated for review comments (None for conversation comments).
    path: str | None
    line: int | None
    start_line: int | None
    side: str | None
    diff_hunk: str | None
    in_reply_to_id: str | None
    commit_id: str | None
    reactions: list[dict[str, Any]]


@dataclass(frozen=True)
class GitHubCommitAuthor:
    login: str
    name: str | None
    commit_url: str
    # GitHub caps the file listing at 300 entries.
    file_paths: tuple[str, ...] = ()
    is_bot: bool = False


@dataclass(frozen=True)
class GitHubCommitAttribution:
    """GitHub's own commit→account attribution, from the commits listing."""

    sha: str
    login: str
    is_bot: bool
    # Git author display name — untrusted free text, for display only, never parse it.
    name: str | None = None


class GitHubIntegrationError(Exception):
    """A GitHub API call failed for a non-rate-limit reason (bad response, auth failure, network
    error after retry). Rate limits raise ``GitHubRateLimitError`` from ``posthog.egress.github``
    instead — a transient limit isn't an integration failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        # Needed, so retry wrappers can make decisions without reparsing the response.
        self.status_code = status_code


def _github_repo_optional_fields(repo: dict) -> dict:
    """Display fields for a repo, taken off the GitHub payload or a cached entry.

    Returns only the keys that are present and well-typed, so repositories cached before these fields
    existed keep their original (id, name, full_name) shape and don't sprout nulls. Handles both the
    raw GitHub shape (nested ``permissions.push``) and the already-flattened cache shape (``can_push``).
    """
    optional: dict = {}
    for key in ("default_branch", "language", "pushed_at"):
        value = repo.get(key)
        if isinstance(value, str):
            optional[key] = value
    for key in ("private", "archived"):
        value = repo.get(key)
        if isinstance(value, bool):
            optional[key] = value
    permissions = repo.get("permissions")
    can_push = permissions.get("push") if isinstance(permissions, dict) else repo.get("can_push")
    if isinstance(can_push, bool):
        optional["can_push"] = can_push
    return optional


class GitHubIntegrationBase:
    """Installation-token operations shared between team and user GitHub integrations."""

    integration: Any  # Integration | UserIntegration -- subclasses narrow the type
    # Per-subsystem attribution on the shared egress metrics. Product callers construct their client
    # with their own source (e.g. GitHubIntegration(integration, source="visual_review")) so every
    # request made through this instance — api_request, verbs, GraphQL — is attributed to them.
    source: str = _OBSERVABILITY_SOURCE
    # How sheddable this instance's calls are when the installation's shared budget runs hot.
    # CRITICAL (the default) is never blocked; deferrable background callers construct with
    # priority=Priority.BATCH so the egress limiter sheds them first — a denied sheddable call
    # raises GitHubEgressBudgetExhausted from api_request before anything is sent.
    priority: Priority = Priority.CRITICAL

    @property
    def github_installation_id(self) -> str | None:
        """The GitHub App installation ID. Override in subclasses where the field name differs."""
        return self.integration.integration_id

    # --- App-level JWT authentication ---

    @classmethod
    def client_request(
        cls,
        endpoint: str,
        method: str = "GET",
        timeout: float | None = 10,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        """Make a request to the GitHub App API using a JWT.

        ``timeout`` defaults to 10s so callers in web request and token-refresh paths
        can't hang indefinitely on an unresponsive GitHub endpoint. Pass an explicit
        value (or ``None`` to disable) when a different bound is needed.
        """
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

        # Identity-blind on purpose: App-JWT calls are metered per App, not per installation, so
        # gating them under an installation budget would be wrong — but volume telemetry still counts.
        return github_request(
            method,
            f"https://api.github.com/app/{endpoint}",
            source=_OBSERVABILITY_SOURCE,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=timeout,
            # requests omits the body entirely when json is None
            json=json_body,
        )

    # --- App installation lifecycle (uninstall) ---

    @staticmethod
    def installation_reference_count(
        installation_id: str,
        *,
        exclude_team_integration_id: int | None = None,
        exclude_user_integration_id: uuid.UUID | None = None,
    ) -> int:
        """Count PostHog rows that reference a GitHub App installation.

        One installation can be shared by many team ``Integration`` rows and many
        personal ``UserIntegration`` rows. Callers pass the id of the row currently
        being deleted via the ``exclude_*`` params so it is not counted against itself.
        """
        # Local imports: both model modules import this module at load time.
        from posthog.models.integration import Integration
        from posthog.models.user_integration import UserIntegration

        team_qs = Integration.objects.filter(kind="github", integration_id=installation_id)
        if exclude_team_integration_id is not None:
            team_qs = team_qs.exclude(id=exclude_team_integration_id)

        user_qs = UserIntegration.objects.filter(kind="github", integration_id=installation_id)
        if exclude_user_integration_id is not None:
            user_qs = user_qs.exclude(id=exclude_user_integration_id)

        return team_qs.count() + user_qs.count()

    @classmethod
    def uninstall_app_installation(cls, installation_id: str) -> bool:
        """Tell GitHub to uninstall the App via ``DELETE /app/installations/{id}``.

        Best-effort: never raises. Treats 204 (removed) and 404 (already gone) as
        success. Returns ``False`` on any other outcome or when the App is not configured.
        """
        if not installation_id:
            return False
        if not settings.GITHUB_APP_CLIENT_ID or not settings.GITHUB_APP_PRIVATE_KEY:
            logger.warning("GitHubIntegration: uninstall skipped, GitHub App not configured")
            return False

        try:
            response = cls.client_request(f"installations/{installation_id}", method="DELETE", timeout=10)
        except Exception:
            logger.warning(
                "GitHubIntegration: uninstall_app_installation request failed",
                installation_id=installation_id,
                exc_info=True,
            )
            return False

        if response.status_code in (204, 404):
            logger.info(
                "GitHubIntegration: uninstalled App installation",
                installation_id=installation_id,
                status_code=response.status_code,
            )
            return True

        logger.warning(
            "GitHubIntegration: uninstall_app_installation unexpected status",
            installation_id=installation_id,
            status_code=response.status_code,
        )
        return False

    @classmethod
    def uninstall_if_last_reference(
        cls,
        installation_id: str,
        *,
        exclude_team_integration_id: int | None = None,
        exclude_user_integration_id: uuid.UUID | None = None,
    ) -> bool:
        """Uninstall the App on GitHub only when no other PostHog row references it."""
        if not installation_id:
            return False

        remaining = cls.installation_reference_count(
            installation_id,
            exclude_team_integration_id=exclude_team_integration_id,
            exclude_user_integration_id=exclude_user_integration_id,
        )
        if remaining > 0:
            logger.info(
                "GitHubIntegration: skipping uninstall, other references remain",
                installation_id=installation_id,
                remaining=remaining,
            )
            return False

        return cls.uninstall_app_installation(installation_id)

    @staticmethod
    def verify_user_installation_access(installation_id: str, user_access_token: str) -> bool:
        """Check that a GitHub user has access to the given App installation.

        Calls ``GET /user/installations/{id}/repositories`` with the user's
        OAuth token.  Returns ``True`` when the user has access, ``False``
        when GitHub returns 404 (no access).  Raises on network errors or
        unexpected status codes so callers can surface an appropriate error.
        """
        # installation_id stays None: this call is authenticated with the *user's* OAuth token, so
        # GitHub meters it against the user's budget, not the installation's — gating or writing
        # gauges under the installation would consume/clobber a budget the call never draws from.
        response = github_request(
            "GET",
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            source=_OBSERVABILITY_SOURCE,
            headers={"Authorization": f"Bearer {user_access_token}"},
            endpoint="/user/installations/{installation_id}/repositories",
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

    def _record_github_cache_access(
        self, cache_type: Literal["repositories", "branches"], result: Literal["hit", "miss"], repository: str
    ) -> None:
        github_cache_access_counter.labels(str(self.integration.id), cache_type, repository.casefold(), result).inc()

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
        # client_request records the call via the egress transport — no manual recording here,
        # or every refresh would count twice.
        response = self.client_request(f"installations/{self.github_installation_id}/access_tokens", method="POST")
        try:
            data = response.json()
        except ValueError:
            self._on_token_refresh_failed(response)
            raise GitHubIntegrationError(
                f"Non-JSON response when refreshing installation token: {response.text[:500]}",
                status_code=response.status_code,
            ) from None

        if response.status_code != 201 or not data.get("token"):
            self._on_token_refresh_failed(response)
            raise GitHubIntegrationError(
                f"Failed to refresh installation token: {response.text}",
                status_code=response.status_code,
            )

        if "expires_at" not in data:
            raise Exception("GitHub API response missing expires_at field")
        try:
            expires_in = datetime.fromisoformat(data["expires_at"]).timestamp() - int(time.time())
        except ValueError as e:
            raise Exception(f"Invalid expires_at format from GitHub: {e}")

        config = {
            **self.integration.config,
            "expires_in": expires_in,
            "refreshed_at": int(time.time()),
        }
        config.pop(INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY, None)
        self.integration.config = config
        self.integration.sensitive_config = {
            **(self.integration.sensitive_config or {}),
            "access_token": data["token"],
        }
        self._on_token_refreshed()
        self.integration.save()

    def mint_scoped_installation_token(
        self,
        permissions: Mapping[str, str],
        repositories: list[str] | None = None,
    ) -> str:
        """Mint an ephemeral installation token downscoped to ``permissions`` (e.g.
        ``{"contents": "read", "metadata": "read"}``) and optionally to ``repositories``
        (bare repo names, no owner prefix).

        The token is returned to the caller and deliberately NOT persisted: the cached
        ``sensitive_config`` token is the shared full-permission credential every other
        flow reads, and overwriting it with a downscoped one would silently break them.
        Scoped tokens expire like any installation token (~1h) and cannot be refreshed —
        mint a new one instead. Requesting a permission the installation doesn't have
        fails the mint (422), which surfaces as ``GitHubIntegrationError``.
        """
        installation_id = self.github_installation_id
        if not installation_id:
            raise GitHubIntegrationError("No GitHub App installation id on this integration")

        body: dict[str, Any] = {"permissions": dict(permissions)}
        if repositories:
            body["repositories"] = repositories

        response = self.client_request(f"installations/{installation_id}/access_tokens", method="POST", json_body=body)
        try:
            data = response.json()
        except ValueError:
            self._mark_if_installation_gone(response)
            raise GitHubIntegrationError(
                f"Non-JSON response when minting scoped installation token: {response.text[:500]}",
                status_code=response.status_code,
            ) from None
        if response.status_code != 201 or not data.get("token"):
            self._mark_if_installation_gone(response)
            raise GitHubIntegrationError(
                f"Failed to mint scoped installation token: {response.text[:500]}",
                status_code=response.status_code,
            )
        return data["token"]

    def _mark_if_installation_gone(self, response: requests.Response) -> None:
        """Persist the permanently-gone marker after a failed scoped mint (404 uninstalled /
        403 suspended), so callers that check :meth:`installation_unavailable` stop re-minting a
        dead installation on every run. Deliberately NOT the full ``_on_token_refresh_failed``
        hook: that one also stamps ``errors`` on transient failures, which would exclude the
        integration from team resolution over a passing GitHub 500."""
        if self._disarm_proactive_refresh_if_installation_gone(response):
            self.integration.save(update_fields=["config"])

    @staticmethod
    def _installation_permanently_unavailable(response: requests.Response) -> bool:
        """Whether a mint response (POST installations/{id}/access_tokens) shows the installation is
        permanently gone — 404 (uninstalled) or a 403 suspension — as opposed to a transient failure.

        A rate-limited 403 is transient and must return False, so a live installation is never mistaken
        for a dead one: the shared :func:`raise_if_github_rate_limited` detector is the single source of
        truth for that, and any 403 it doesn't flag as a rate limit is only treated as suspension when
        the body says so. When in doubt, return False and leave the row armed.
        """
        if response.status_code == 404:
            return True
        if response.status_code != 403:
            return False
        try:
            raise_if_github_rate_limited(response)
        except GitHubRateLimitError:
            return False
        try:
            body = (response.text or "").lower()
        except Exception:
            body = ""
        return "suspended" in body

    def _disarm_proactive_refresh_if_installation_gone(self, response: requests.Response) -> bool:
        """Stop the every-minute beat loop from re-minting a dead installation forever.

        ``access_token_expired()`` returns False when ``config`` lacks ``expires_in``/``refreshed_at``,
        so dropping those two keys permanently disarms proactive refresh for this row. Only fires for a
        permanently-gone installation (404 uninstalled / 403 suspended), never a transient failure.
        Also stamps ``installation_unavailable_since`` so callers can distinguish a dead installation's
        stale stored token from a usable one (see :meth:`installation_unavailable`).
        Self-healing: if the installation is later restored, a real API call 401s and ``api_request``'s
        refresh-retry mints successfully, re-persists the fields, and clears the marker. Mutates
        ``config`` in memory and returns whether anything changed; the caller owns the save.
        """
        if not self._installation_permanently_unavailable(response):
            return False
        config = {**self.integration.config}
        changed = False
        if "expires_in" in config or "refreshed_at" in config:
            config.pop("expires_in", None)
            config.pop("refreshed_at", None)
            changed = True
        if INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY not in config:
            config[INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY] = int(time.time())
            changed = True
        if changed:
            self.integration.config = config
        return changed

    def installation_unavailable(self) -> bool:
        """Whether a failed mint marked this installation permanently gone (uninstalled or
        suspended) and no mint has succeeded since. While True, the stored access token is
        stale — it survives disarming but GitHub will reject it once it expires server-side."""
        return bool(self.integration.config.get(INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY))

    def _on_token_refresh_failed(self, response: requests.Response) -> None:
        """Called when the installation token refresh request fails.

        Override to persist error state, increment counters, etc.  The base
        implementation logs and, for a permanently-gone installation, disarms the
        every-minute proactive refresh so a dead row isn't re-minted forever.
        """
        logger.warning(
            "GitHubIntegration: installation token refresh failed",
            integration_id=self.integration.id,
            status_code=response.status_code,
        )
        if self._disarm_proactive_refresh_if_installation_gone(response):
            self.integration.save(update_fields=["config"])

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
        self,
        url: str,
        *,
        endpoint: str,
        params: dict[str, str | int] | None = None,
        timeout: int = 10,
    ) -> requests.Response | None:
        """GET with installation token via :meth:`api_request`; ``None`` instead of raising, for the
        success/error-dict verbs built on top."""
        path = url.removeprefix("https://api.github.com")
        try:
            return self.api_request("GET", path, endpoint=endpoint, params=params, timeout=timeout)
        except GitHubIntegrationError:
            logger.warning("GitHubIntegration: installation GET failed", url=url, exc_info=True)
            return None

    def _installation_authenticated_get_pages(
        self,
        url: str,
        *,
        endpoint: str,
        params: dict[str, str | int] | None = None,
        timeout: int = 10,
    ) -> tuple[list[requests.Response], bool]:
        """Follow GitHub's trusted ``next`` links and report whether every page was fetched."""
        responses: list[requests.Response] = []
        next_url = url
        next_params = params
        seen_urls: set[str] = set()

        while True:
            if next_url in seen_urls:
                return responses, False
            seen_urls.add(next_url)
            response = self._installation_authenticated_get(
                next_url,
                endpoint=endpoint,
                params=next_params,
                timeout=timeout,
            )
            if response is None:
                return responses, False
            responses.append(response)
            if response.status_code != 200:
                return responses, False

            links = getattr(response, "links", None)
            next_link = links.get("next") if isinstance(links, dict) else None
            if next_link is None:
                return responses, True
            next_link_url = next_link.get("url") if isinstance(next_link, dict) else None
            if not isinstance(next_link_url, str):
                return responses, False
            parsed_next_url = urlparse(next_link_url)
            if parsed_next_url.scheme != "https" or parsed_next_url.netloc != "api.github.com":
                return responses, False
            next_url = next_link_url
            next_params = None

    def _installation_authenticated_patch(
        self,
        url: str,
        *,
        endpoint: str,
        json_body: Mapping[str, object],
        timeout: int = 10,
    ) -> requests.Response | None:
        """PATCH with installation token via :meth:`api_request`; ``None`` instead of raising, for the
        success/error-dict verbs built on top."""
        path = url.removeprefix("https://api.github.com")
        try:
            return self.api_request("PATCH", path, endpoint=endpoint, json_body=json_body, timeout=timeout)
        except GitHubIntegrationError:
            logger.warning("GitHubIntegration: installation PATCH failed", url=url, exc_info=True)
            return None

    def _installation_authenticated_post(
        self,
        url: str,
        *,
        endpoint: str,
        json_body: Mapping[str, object],
        timeout: int = 10,
    ) -> requests.Response | None:
        """POST with installation token via :meth:`api_request`; ``None`` instead of raising, for the
        success/error-dict verbs built on top."""
        path = url.removeprefix("https://api.github.com")
        try:
            return self.api_request("POST", path, endpoint=endpoint, json_body=json_body, timeout=timeout)
        except GitHubIntegrationError:
            logger.warning("GitHubIntegration: installation POST failed", url=url, exc_info=True)
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

    def list_teams(self, *, search: str = "", limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], bool]:
        """List GitHub teams for the integration account organization with bounded API calls."""
        account = self.integration.config.get("account", {})
        organization = account.get("name", "") if isinstance(account, dict) else ""
        if not organization:
            return [], False

        per_page = 100
        search_lower = search.lower().strip()

        if search_lower:
            # GitHub's org teams endpoint does not support server-side search.
            # Keep calls bounded and shift the fetch window by offset.
            max_pages = 10
            first_page = offset // per_page + 1
            last_page = first_page + max_pages - 1
            start = 0
            end = limit + 1
        else:
            requested = limit + 1
            first_page = offset // per_page + 1
            last_page = (offset + requested) // per_page + 1
            start = offset % per_page
            end = start + requested

        teams: list[dict[str, Any]] = []

        for page in range(first_page, last_page + 1):
            response = self._installation_authenticated_get(
                f"https://api.github.com/orgs/{organization}/teams?page={page}&per_page={per_page}",
                endpoint="/orgs/{org}/teams",
            )
            if response is None or response.status_code != 200:
                logger.warning(
                    "GitHubIntegration: list_teams failed",
                    integration_id=self.integration.id,
                    organization=organization,
                    status_code=response.status_code if response is not None else None,
                )
                raise GitHubIntegrationError("GitHubIntegration: list_teams failed")

            body = response.json()
            if not isinstance(body, list):
                logger.warning(
                    "GitHubIntegration: list_teams invalid payload",
                    integration_id=self.integration.id,
                    organization=organization,
                )
                raise GitHubIntegrationError("GitHubIntegration: list_teams invalid payload")

            for team in body:
                if not isinstance(team, dict):
                    continue
                team_id = team.get("id")
                slug = team.get("slug")
                name = team.get("name")
                if not isinstance(team_id, int) or not isinstance(slug, str) or not isinstance(name, str):
                    continue
                teams.append({"id": team_id, "slug": slug, "name": name})

            if len(body) < per_page:
                break

        if search_lower:
            teams = [
                team for team in teams if search_lower in team["slug"].lower() or search_lower in team["name"].lower()
            ]

        window = teams[start:end]
        has_more = len(window) > limit
        return window[:limit], has_more

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
        files = data.get("files")
        file_paths = (
            tuple(f["filename"] for f in files if isinstance(f, dict) and isinstance(f.get("filename"), str))
            if isinstance(files, list)
            else ()
        )
        return GitHubCommitAuthor(
            login=author["login"],
            name=name,
            commit_url=commit_url,
            file_paths=file_paths,
            is_bot=author.get("type") == "Bot",
        )

    def list_commit_attributions(
        self,
        repository: str,
        *,
        since: datetime,
        # The listing includes merge commits, so it must run deeper than the non-merge
        # git log it joins against (posthog/posthog: ~11k listed entries per 90 days).
        max_pages: int = 150,
    ) -> list[GitHubCommitAttribution]:
        """GitHub's commit→login attribution for default-branch commits since ``since``.

        The listing endpoint carries no file data — callers join on sha against their own
        source of changed paths (e.g. a local ``git log``). Commits GitHub cannot attribute
        to an account (unrecognized author emails) are skipped. The first page failing
        raises; later pages are best-effort so a long history returns what was fetched.
        Rate limits raise ``GitHubRateLimitError`` (from ``api_request``).
        """
        params: dict[str, str | int] = {
            "per_page": 100,
            "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        attributions: list[GitHubCommitAttribution] = []
        for page in range(1, max(1, max_pages) + 1):
            response = self.api_request(
                "GET",
                f"/repos/{repository}/commits",
                endpoint="/repos/{owner}/{repo}/commits",
                params={**params, "page": page},
            )
            if response.status_code != 200:
                if page == 1:
                    raise GitHubIntegrationError(
                        f"GitHubIntegration: commit listing failed for {repository}",
                        status_code=response.status_code,
                    )
                logger.info(
                    "GitHub API non-200 during commit listing pagination",
                    status_code=response.status_code,
                    repository=repository,
                    page=page,
                )
                break
            try:
                body = response.json()
                if not isinstance(body, list):
                    raise ValueError(f"expected a list, got {type(body).__name__}")
            except Exception as exc:
                # Page 1 must raise like the non-200 branch — an empty result here would
                # let callers write an empty attribution map as if it were real data.
                if page == 1:
                    raise GitHubIntegrationError(
                        f"GitHubIntegration: malformed commit listing for {repository}",
                        status_code=response.status_code,
                    ) from exc
                logger.warning(
                    "GitHubIntegration: malformed commit listing page", repository=repository, page=page, exc_info=True
                )
                break
            for entry in body:
                if not isinstance(entry, dict):
                    continue
                sha = entry.get("sha")
                author = entry.get("author")
                if not isinstance(sha, str) or not isinstance(author, dict) or not author.get("login"):
                    continue
                git_author = (entry.get("commit") or {}).get("author") or {}
                attributions.append(
                    GitHubCommitAttribution(
                        sha=sha,
                        login=author["login"],
                        is_bot=author.get("type") == "Bot",
                        name=git_author.get("name") if isinstance(git_author.get("name"), str) else None,
                    )
                )
            if len(body) < 100:
                break
        return attributions

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

    def close_pull_request(self, repository: str, pr_number: int) -> dict[str, Any]:
        """Close a pull request (``PATCH`` state=closed). ``repository`` is ``owner/repo`` or a bare repo.

        Idempotent: an already-closed or merged PR reports success without reopening it (GitHub
        ignores a closed→closed transition, and closing a merged PR is a no-op).
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        response = self._installation_authenticated_patch(
            f"https://api.github.com/repos/{repo_path}/pulls/{pr_number}",
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
            json_body={"state": "closed"},
        )
        if response is None:
            return {"success": False, "error": "Network error closing pull request"}
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Failed to close pull request: {response.text}",
                "status_code": response.status_code,
            }

        try:
            pr = response.json()
        except Exception:
            pr = {}

        return {"success": True, "number": pr.get("number", pr_number), "state": pr.get("state")}

    def close_pull_request_from_url(self, pr_url: str) -> dict[str, Any]:
        """Close a pull request by its HTML URL (e.g. ``https://github.com/owner/repo/pull/123``)."""
        parsed = self.parse_pull_request_url(pr_url)
        if parsed is None:
            return {"success": False, "error": f"Invalid GitHub pull request URL: {pr_url}"}
        owner, repo, pr_number = parsed
        return self.close_pull_request(f"{owner}/{repo}", pr_number)

    def comment_on_pull_request(self, repository: str, pr_number: int, body: str) -> dict[str, Any]:
        """Post a comment on a pull request. ``repository`` is ``owner/repo`` or a bare repo.

        PR comments use the issues endpoint (a PR is an issue for commenting purposes).
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        response = self._installation_authenticated_post(
            f"https://api.github.com/repos/{repo_path}/issues/{pr_number}/comments",
            endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json_body={"body": body},
        )
        if response is None:
            return {"success": False, "error": "Network error commenting on pull request"}
        if response.status_code != 201:
            return {
                "success": False,
                "error": f"Failed to comment on pull request: {response.text}",
                "status_code": response.status_code,
            }
        try:
            created_id = response.json().get("id")
        except Exception:
            created_id = None
        return {"success": True, "id": created_id}

    def comment_on_pull_request_from_url(self, pr_url: str, body: str) -> dict[str, Any]:
        """Post a comment on a pull request by its HTML URL."""
        parsed = self.parse_pull_request_url(pr_url)
        if parsed is None:
            return {"success": False, "error": f"Invalid GitHub pull request URL: {pr_url}"}
        owner, repo, pr_number = parsed
        return self.comment_on_pull_request(f"{owner}/{repo}", pr_number, body)

    def get_pull_request_checks(self, repository: str, pr_number: int) -> dict[str, Any]:
        """Fetch the CI status for a PR — GitHub Actions check runs plus commit statuses from external
        CI and GitHub Apps, merged into one normalized list (mirrors the checks GitHub shows on the PR page).

        Returns ``{"success": True, "checks": [...]}`` on success, or ``{"success": False, "error": ...}``
        on a handled failure. Rate limits raise :class:`GitHubRateLimitError`.
        """
        pr = self.get_pull_request(repository, pr_number)
        if not pr.get("success"):
            return {"success": False, "error": pr.get("error", "Failed to fetch pull request")}
        head_sha = pr.get("head_sha")
        if not head_sha:
            return {"success": False, "error": "Pull request has no head commit"}
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        checks: list[dict[str, Any]] = []

        # GitHub Actions (and any Checks-API app) — the primary source for a modern repo.
        runs_responses, runs_complete = self._installation_authenticated_get_pages(
            f"https://api.github.com/repos/{repo_path}/commits/{head_sha}/check-runs",
            endpoint="/repos/{owner}/{repo}/commits/{ref}/check-runs",
            params={"per_page": 100},
        )
        if not runs_complete:
            return {"success": False, "error": "GitHub could not return every check run"}
        for runs_response in runs_responses:
            try:
                runs_body = runs_response.json()
            except Exception:
                logger.warning("GitHubIntegration: check-runs non-JSON response", repository=repo_path)
                runs_body = {}
            for run in (runs_body.get("check_runs") if isinstance(runs_body, dict) else None) or []:
                if not isinstance(run, dict):
                    continue
                checks.append(
                    {
                        "name": run.get("name") or "check",
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "url": run.get("html_url") or run.get("details_url"),
                    }
                )

        # Commit statuses remain the mechanism used by external CI and GitHub Apps, including our Visual
        # Review integration. The Statuses API returns them separately from Checks-API check runs.
        status_responses, statuses_complete = self._installation_authenticated_get_pages(
            f"https://api.github.com/repos/{repo_path}/commits/{head_sha}/status",
            endpoint="/repos/{owner}/{repo}/commits/{ref}/status",
            params={"per_page": 100},
        )
        if not statuses_complete:
            return {"success": False, "error": "GitHub could not return every commit status"}
        for status_response in status_responses:
            try:
                status_body = status_response.json()
            except Exception:
                logger.warning("GitHubIntegration: commit-status non-JSON response", repository=repo_path)
                status_body = {}
            for st in (status_body.get("statuses") if isinstance(status_body, dict) else None) or []:
                if not isinstance(st, dict):
                    continue
                mapped_status, mapped_conclusion = self._map_commit_status_state(st.get("state"))
                checks.append(
                    {
                        "name": st.get("context") or "status",
                        "status": mapped_status,
                        "conclusion": mapped_conclusion,
                        "url": st.get("target_url"),
                    }
                )

        return {"success": True, "checks": checks}

    @staticmethod
    def _map_commit_status_state(state: str | None) -> tuple[str, str | None]:
        """Map a commit-status ``state`` onto the check-run ``(status, conclusion)`` shape."""
        if state == "success":
            return "completed", "success"
        if state in ("failure", "error"):
            return "completed", "failure"
        return "in_progress", None

    @staticmethod
    def normalize_pr_comment(raw: object, comment_type: str) -> NormalizedPRComment | None:
        """Shape a raw GitHub comment into the wire contract shared by the read path and the write
        endpoints. ``reactions`` is left empty; the read path fills it for review comments that have any."""
        if not isinstance(raw, dict):
            return None
        user = raw.get("user") or {}
        is_review = comment_type == "review"
        return {
            # Direct access on the primary key: a GitHub comment always carries an `id`, and
            # coercing a missing one to the string "None" would collide as a React key downstream.
            "id": str(raw["id"]),
            "author": user.get("login"),
            "author_avatar_url": user.get("avatar_url"),
            "body": raw.get("body") or "",
            "created_at": raw.get("created_at"),
            "url": raw.get("html_url"),
            "comment_type": comment_type,
            # Only review comments are anchored to a file position in the diff.
            "path": raw.get("path") if is_review else None,
            "line": raw.get("line") if is_review else None,
            "start_line": raw.get("start_line") if is_review else None,
            "side": raw.get("side") if is_review else None,
            "diff_hunk": raw.get("diff_hunk") if is_review else None,
            "in_reply_to_id": str(raw["in_reply_to_id"]) if is_review and raw.get("in_reply_to_id") else None,
            "commit_id": raw.get("commit_id") if is_review else None,
            "reactions": [],
        }

    def get_pull_request_comments(self, repository: str, pr_number: int) -> dict[str, Any]:
        """Fetch a PR's conversation comments and inline review comments, merged chronologically.

        Returns ``{"success": True, "comments": [...]}`` on success, or ``{"success": False, "error": ...}``
        on a handled failure. Rate limits raise :class:`GitHubRateLimitError`. Best-effort per source:
        a failure fetching one comment kind still returns whatever the other kind yielded.
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        comments: list[NormalizedPRComment] = []
        for path, comment_type, endpoint in (
            (f"issues/{pr_number}/comments", "conversation", "/repos/{owner}/{repo}/issues/{issue_number}/comments"),
            (f"pulls/{pr_number}/comments", "review", "/repos/{owner}/{repo}/pulls/{pull_number}/comments"),
        ):
            responses, _complete = self._installation_authenticated_get_pages(
                f"https://api.github.com/repos/{repo_path}/{path}",
                endpoint=endpoint,
                params={"per_page": 100},
            )
            for response in responses:
                if response.status_code != 200:
                    continue
                try:
                    body = response.json()
                except Exception:
                    logger.warning(
                        "GitHubIntegration: get_pull_request_comments non-JSON response", repository=repo_path
                    )
                    continue
                if not isinstance(body, list):
                    continue
                for raw in body:
                    normalized = self.normalize_pr_comment(raw, comment_type)
                    if normalized is None:
                        continue
                    if comment_type == "review":
                        reaction_summary = raw.get("reactions") or {}
                        if isinstance(reaction_summary, dict) and reaction_summary.get("total_count"):
                            normalized["reactions"] = self._get_review_comment_reactions(repo_path, str(raw["id"]))
                    comments.append(normalized)

        # Merge both streams into a single chronological thread; entries without a timestamp sort last.
        comments.sort(key=lambda c: c.get("created_at") or "")
        return {"success": True, "comments": comments}

    def _get_review_comment_reactions(self, repo_path: str, comment_id: str) -> list[dict[str, Any]]:
        """Fetch a review comment's reactions, each with its id, content, and reactor login.

        Returned per-reactor (not just counts) so the frontend can group them, highlight the viewer's
        own, and delete them by id. Best-effort: returns [] on any non-200 / parse failure.
        """
        try:
            responses, _complete = self._installation_authenticated_get_pages(
                f"https://api.github.com/repos/{repo_path}/pulls/comments/{comment_id}/reactions",
                endpoint="/repos/{owner}/{repo}/pulls/comments/{comment_id}/reactions",
                params={"per_page": 100},
            )
        except Exception:
            logger.warning("GitHubIntegration: reactions fetch failed", repository=repo_path, comment_id=comment_id)
            return []
        out: list[dict[str, Any]] = []
        for response in responses:
            if response.status_code != 200:
                continue
            try:
                body = response.json()
            except Exception:
                continue
            if not isinstance(body, list):
                continue
            for reaction in body:
                if isinstance(reaction, dict) and reaction.get("content") and reaction.get("id") is not None:
                    out.append(
                        {
                            "id": str(reaction["id"]),
                            "content": reaction["content"],
                            "user_login": (reaction.get("user") or {}).get("login"),
                        }
                    )
        return out

    def add_reaction_to_comment(self, repository: str, comment_id: int, content: str = "eyes") -> dict[str, Any]:
        """React to an issue/PR conversation comment (e.g. an "eyes" ack). ``repository`` is
        ``owner/repo`` or a bare repo. GitHub returns 200 if the reaction already existed, 201 if created."""
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"

        response = self._installation_authenticated_post(
            f"https://api.github.com/repos/{repo_path}/issues/comments/{comment_id}/reactions",
            endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions",
            json_body={"content": content},
        )
        if response is None:
            return {"success": False, "error": "Network error adding reaction"}
        if response.status_code not in (200, 201):
            return {
                "success": False,
                "error": f"Failed to add reaction: {response.text}",
                "status_code": response.status_code,
            }
        return {"success": True}

    def list_pull_request_comments(self, repository: str, pr_number: int, *, max_pages: int = 10) -> dict[str, Any]:
        """List conversation (issue) comments on a PR, following pagination up to ``max_pages`` (100/page).

        Returns ``{"success": True, "comments": [...]}`` where each comment carries ``id``, ``body``,
        ``author_login``, ``author_id``, ``created_at``, and ``performed_via_github_app`` (True when the
        comment was authored by a GitHub App — used to skip the bot's own comments). Inline review
        comments live on a different endpoint and are intentionally excluded.
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        comments: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            response = self._installation_authenticated_get(
                f"https://api.github.com/repos/{repo_path}/issues/{pr_number}/comments",
                endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
                params={"per_page": 100, "page": page},
            )
            if response is None:
                return {"success": False, "error": "Network error listing pull request comments"}
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to list pull request comments: {response.text}",
                    "status_code": response.status_code,
                }
            try:
                page_items = response.json()
            except Exception:
                return {"success": False, "error": "Failed to parse pull request comments JSON"}
            if not isinstance(page_items, list):
                return {"success": False, "error": "Unexpected pull request comments payload"}
            for item in page_items:
                user = item.get("user") or {}
                comments.append(
                    {
                        "id": item.get("id"),
                        "body": item.get("body") or "",
                        "author_login": user.get("login"),
                        "author_id": user.get("id"),
                        "created_at": item.get("created_at"),
                        "performed_via_github_app": item.get("performed_via_github_app") is not None,
                    }
                )
            if len(page_items) < 100:
                break
        return {"success": True, "comments": comments}

    def find_pull_request_urls_for_branch(self, repository: str, branch: str) -> list[str]:
        """Return the HTML URLs of open or closed PRs whose head is ``branch`` in ``repository``.

        ``repository`` is ``owner/repo`` (or a bare repo, resolved against the org). Results come
        from the installation token's own API call, so they are inherently trusted — not
        user-supplied like ``output.pr_url``. Best-effort: returns [] on a bad repo, non-200, or
        error — except rate limits (``GitHubRateLimitError``) and, on a sheddable instance, budget
        denial (``GitHubEgressBudgetExhausted``), which raise so callers can defer the sweep.
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        owner = repo_path.split("/", 1)[0]
        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repo_path}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "all", "per_page": 10},
        )
        if response is None or response.status_code != 200:
            return []
        try:
            pulls = response.json()
        except Exception:
            logger.warning(
                "GitHubIntegration: find_pull_request_urls_for_branch non-JSON response", repository=repo_path
            )
            return []
        if not isinstance(pulls, list):
            return []
        return [pr["html_url"] for pr in pulls if isinstance(pr, dict) and isinstance(pr.get("html_url"), str)]

    def get_open_pr_base_for_head(self, repository: str, branch: str) -> str | None:
        """Return the base branch of an OPEN pull request whose head is ``branch``, if one exists.

        ``repository`` is ``owner/repo`` (or a bare repo, resolved against the org). Distinguishes
        a branch that *heads* an open PR (work continues on it) from a branch used as a PR *base*.
        Best-effort: returns None on a bad repo, non-200, no open PR, or any error.
        """
        repo_path = repository if "/" in repository else f"{self.organization()}/{repository}"
        owner = repo_path.split("/", 1)[0]
        response = self._installation_authenticated_get(
            f"https://api.github.com/repos/{repo_path}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open", "per_page": 1},
        )
        if response is None or response.status_code != 200:
            return None
        try:
            pulls = response.json()
        except Exception:
            logger.warning("GitHubIntegration: get_open_pr_base_for_head non-JSON response", repository=repo_path)
            return None
        if not isinstance(pulls, list) or not pulls or not isinstance(pulls[0], dict):
            return None
        base = (pulls[0].get("base") or {}).get("ref")
        return base if isinstance(base, str) and base else None

    _PR_SNAPSHOT_QUERY = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $number) {
          number title url state isDraft mergeable updatedAt headRefName headRefOid
          author { login }
          reviewDecision
          reviewRequests(first: 50) {
            nodes { requestedReviewer { __typename ... on User { login } ... on Team { slug } } }
          }
          reviewThreads(first: 100) { nodes { isResolved } }
          commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
        }
      }
    }
    """

    # GitHub surfaces its own transient server errors not as a 5xx but as an HTTP 200 with
    # ``data: null`` and an ``errors`` body — the documented "Something went wrong while
    # executing your query" class, plus ``SERVICE_UNAVAILABLE``/timeout errors. Because the
    # HTTP status is 200, :meth:`api_request`'s status-code retry never sees them, so we detect
    # and retry them here. They are safe to repeat (GraphQL reads are idempotent and the query
    # never executed); deterministic field-level errors (permissions, validation) are not.
    _TRANSIENT_GRAPHQL_ERROR_TYPES = frozenset({"SERVICE_UNAVAILABLE"})
    _TRANSIENT_GRAPHQL_ERROR_MESSAGES = ("something went wrong while executing your query",)
    # Total GraphQL attempts (initial + retries) when GitHub returns a transient body error.
    _GRAPHQL_TRANSIENT_ATTEMPTS = 3

    @classmethod
    def _graphql_errors_are_transient(cls, errors: list) -> bool:
        """True when the GraphQL ``errors`` body is one of GitHub's retryable server-side failures.

        Conservative: any single error that isn't a known transient class (e.g. a field-level
        permission or validation error) makes the whole response non-retryable, so we never
        loop on a deterministic failure.
        """
        if not errors:
            return False
        for error in errors:
            if not isinstance(error, dict):
                return False
            if error.get("type") in cls._TRANSIENT_GRAPHQL_ERROR_TYPES:
                continue
            message = str(error.get("message", "")).lower()
            if any(marker in message for marker in cls._TRANSIENT_GRAPHQL_ERROR_MESSAGES):
                continue
            return False
        return True

    def _gh_graphql(self, query: str, variables: dict[str, Any], *, endpoint: str, timeout: int = 10) -> dict:
        """Authenticated POST to the GitHub GraphQL API. Returns the ``data`` object.

        GraphQL queries are read-only, so a POST retry on transient failures is safe —
        hence ``retry_transient=True`` on the shared :meth:`api_request` lifecycle, plus an
        extra retry loop here for GitHub's 200-with-``errors`` transient server errors that
        the status-code retry can't catch.
        """
        errors: Any = None
        for attempt in range(self._GRAPHQL_TRANSIENT_ATTEMPTS):
            response = self.api_request(
                "POST",
                "/graphql",
                endpoint=endpoint,
                json_body={"query": query, "variables": variables},
                timeout=timeout,
                retry_transient=True,
            )
            if response.status_code != 200:
                raise GitHubIntegrationError(
                    f"GitHubIntegration: _gh_graphql {response.status_code} on {endpoint}: {response.text[:300]}",
                    status_code=response.status_code,
                )
            body = response.json()
            data = body.get("data")
            errors = body.get("errors")
            if not errors:
                return data or {}
            if data:
                # GitHub can return useful partial data with field-level permission errors.
                logger.warning("GitHubIntegration: GraphQL partial errors", endpoint=endpoint, errors=errors)
                return data
            # No data — a hard failure. Retry GitHub's transient server errors; raise the rest.
            if not self._graphql_errors_are_transient(errors):
                break
            if attempt < self._GRAPHQL_TRANSIENT_ATTEMPTS - 1:
                logger.info(
                    "GitHubIntegration: retrying transient GraphQL error",
                    endpoint=endpoint,
                    attempt=attempt,
                    errors=errors,
                )
        raise GitHubIntegrationError(f"GitHubIntegration: GraphQL errors on {endpoint}: {errors}")

    @staticmethod
    def _map_pr_state(gql_state: str | None, is_draft: bool) -> str:
        if gql_state == "MERGED":
            return "merged"
        if gql_state == "CLOSED":
            return "closed"
        if is_draft:
            return "draft"
        return "open"

    @staticmethod
    def _map_ci_status(rollup_state: str | None) -> str:
        if rollup_state == "SUCCESS":
            return "passing"
        if rollup_state in ("FAILURE", "ERROR"):
            return "failing"
        if rollup_state in ("PENDING", "EXPECTED"):
            return "pending"
        return "none"

    @staticmethod
    def _map_mergeable(gql_mergeable: str | None) -> bool | None:
        if gql_mergeable == "MERGEABLE":
            return True
        if gql_mergeable == "CONFLICTING":
            return False
        return None

    def get_pull_request_snapshot(self, pr_url: str) -> dict[str, Any]:
        """Fetch the classification-relevant PR signals in one GraphQL call.

        On any handled failure returns ``{"success": False, "error": ...}``; unexpected errors
        raise ``GitHubIntegrationError``. GitHub rate limits raise ``GitHubRateLimitError``, and on
        a sheddable instance (``priority=NORMAL/BATCH``) a denied budget raises
        ``GitHubEgressBudgetExhausted`` — callers own the back-off for both.
        """
        parsed = self.parse_pull_request_url(pr_url)
        if parsed is None:
            return {"success": False, "error": f"Invalid GitHub pull request URL: {pr_url}"}
        owner, repo, pr_number = parsed

        data = self._gh_graphql(
            self._PR_SNAPSHOT_QUERY,
            {"owner": owner, "repo": repo, "number": pr_number},
            endpoint="/graphql:pullRequestSnapshot",
        )
        pr = ((data or {}).get("repository") or {}).get("pullRequest")
        if not pr:
            return {"success": False, "error": f"Pull request not found: {pr_url}"}

        rollup_nodes = ((pr.get("commits") or {}).get("nodes")) or []
        rollup_state = None
        if rollup_nodes:
            rollup_state = ((rollup_nodes[0].get("commit") or {}).get("statusCheckRollup") or {}).get("state")

        thread_nodes = ((pr.get("reviewThreads") or {}).get("nodes")) or []
        unresolved_threads = sum(1 for t in thread_nodes if t and t.get("isResolved") is False)

        reviewer_logins: list[str] = []
        for node in ((pr.get("reviewRequests") or {}).get("nodes")) or []:
            reviewer = (node or {}).get("requestedReviewer") or {}
            login = reviewer.get("login") or reviewer.get("slug")
            if login:
                reviewer_logins.append(login)

        review_decision = pr.get("reviewDecision")
        author = (pr.get("author") or {}).get("login")

        return {
            "success": True,
            "number": pr.get("number"),
            "title": pr.get("title") or "",
            "url": pr.get("url") or pr_url,
            "state": self._map_pr_state(pr.get("state"), bool(pr.get("isDraft"))),
            "ci_status": self._map_ci_status(rollup_state),
            "review_decision": review_decision.lower() if isinstance(review_decision, str) else None,
            "unresolved_threads": unresolved_threads,
            "mergeable": self._map_mergeable(pr.get("mergeable")),
            "author_login": author,
            "head_branch": pr.get("headRefName"),
            "head_sha": pr.get("headRefOid"),
            "requested_reviewer_logins": reviewer_logins,
            "updated_at": pr.get("updatedAt"),
        }

    def list_repositories(self, *, page: int = 1, per_page: int = 100) -> tuple[list[dict], bool]:
        """List one page of installation repositories from the GitHub API.

        Uses GitHub's ``page`` and ``per_page`` query parameters
        (``per_page`` is clamped to 1–100, the API maximum). Returns
        ``(repositories, has_more)`` where *has_more* is true when the page is
        full, so another page may exist.
        """
        page = max(1, page)
        per_page = max(1, min(100, per_page))

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
                    **_github_repo_optional_fields(repo),
                }
                for repo in repositories
                if isinstance(repo, dict)
                and isinstance(repo.get("id"), int)
                and isinstance(repo.get("name"), str)
                and isinstance(repo.get("full_name"), str)
            ]

        response = self.api_request(
            "GET",
            f"/installation/repositories?page={page}&per_page={per_page}",
            endpoint="/installation/repositories",
        )
        try:
            body = response.json()
        except Exception:
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
        logger.warning(
            "GitHubIntegration: failed to list repositories",
            integration_id=self.integration.id,
            status_code=response.status_code,
            error=body if isinstance(body, dict) else None,
        )
        raise GitHubIntegrationError("GitHubIntegration: failed to list repositories")

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

        def fetch(page: int) -> requests.Response:
            return self.api_request(
                "GET",
                f"/repos/{repo}/branches?per_page={GITHUB_PER_PAGE}&page={page}",
                endpoint="/repos/{owner}/{repo}/branches",
            )

        def extract_names(data: list) -> list[str]:
            return [
                branch["name"] for branch in data if isinstance(branch, dict) and isinstance(branch.get("name"), str)
            ]

        # Work out which GitHub pages cover the requested window.
        first_page = offset // GITHUB_PER_PAGE + 1
        skip = offset % GITHUB_PER_PAGE
        needed = skip + limit

        # Fetch the first required page.
        current_page = first_page
        try:
            response = fetch(current_page)
        except GitHubIntegrationError:
            logger.warning("GitHubIntegration: list_branches request failed", repo=repo, exc_info=True)
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
            except GitHubIntegrationError:
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
            response = self.api_request(
                "GET", "/installation/repositories?page=1&per_page=100", endpoint="/installation/repositories"
            )
        except GitHubIntegrationError:
            logger.warning("GitHubIntegration: get_top_starred_repository request failed", exc_info=True)
            return None

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

        response = self.api_request("GET", f"/repos/{repo_path}", endpoint="/repos/{owner}/{repo}")

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
                **_github_repo_optional_fields(repo),
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

    def get_access_token(self) -> str:
        """Return a valid installation access token, refreshing it past the half-life threshold."""
        if self.access_token_expired():
            try:
                self.refresh_access_token()
            except Exception:
                # The refresh threshold is the token's half-life, so the stored token is typically
                # still valid — use it rather than failing the request on a transient App-endpoint
                # error; a genuinely dead token gets the 401 refresh-retry as the backstop.
                logger.warning("GitHubIntegration: proactive token refresh failed, using stored token", exc_info=True)
        token = (self.integration.sensitive_config or {}).get("access_token")
        if not token:
            raise GitHubIntegrationError("Access token unavailable after refresh")
        return token

    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        json_body: Mapping[str, object] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 10,
        retry_transient: bool | None = None,
        priority: Priority | None = None,
    ) -> requests.Response:
        """Authenticated request against ``https://api.github.com`` returning the raw response.

        Owns the shared token lifecycle — proactive refresh, one refresh-retry on 401, and one retry
        on a transient network error or 5xx where a repeat is safe (``retry_transient`` defaults to
        GET only; read-only POSTs like GraphQL opt in). Raises :class:`GitHubRateLimitError` when
        GitHub rate-limits the call; every other response is returned as-is for the caller's
        status-driven handling. ``_gh_api_get`` layers JSON parsing and non-2xx raising on top for
        callers that want dict-or-raise semantics.

        ``endpoint`` is the normalized label for egress telemetry; leave it ``None`` to let the
        recorder template the raw URL. Attribution uses ``self.source``; the limiter lane defaults
        to ``self.priority`` — on a sheddable lane (NORMAL/BATCH) a denied call raises
        ``GitHubEgressBudgetExhausted`` instead of being sent, and the caller owns the deferral.
        """
        if not path.startswith("/"):
            raise ValueError(f"api_request path must start with '/', got {path!r}")
        url = f"https://api.github.com{path}"
        transient_status_codes = {502, 503, 504}
        if retry_transient is None:
            retry_transient = method.upper() == "GET"
        # Proactively refresh expiring tokens (failure here is non-fatal — the loop retries on 401).
        try:
            if self.access_token_expired():
                self.refresh_access_token()
        except Exception:
            logger.warning("GitHubIntegration: token refresh pre-check failed", exc_info=True)

        for attempt in range(2):
            # Outside the try: a failing token refresh must fail fast, not be retried as a
            # transient network error.
            token = self.get_access_token()
            try:
                response = github_request(
                    method,
                    url,
                    source=self.source,
                    # Token last: a caller-supplied Authorization must not bypass the managed lifecycle.
                    headers={**(headers or {}), "Authorization": f"Bearer {token}"},
                    installation_id=self.github_installation_id,
                    priority=priority if priority is not None else self.priority,
                    endpoint=endpoint,
                    params=params,
                    json=json_body,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                if retry_transient and attempt == 0:
                    logger.info(
                        "GitHubIntegration: api_request retrying network error",
                        path=path,
                        exc_info=True,
                    )
                    continue
                raise GitHubIntegrationError(f"GitHubIntegration: api_request network error on {path}") from exc
            # Successful installation-token responses are the only trusted source of the tier the
            # limiter budgets to; the store filters non-2xx/non-core itself.
            remember_observed_core_limit(self.github_installation_id, response)
            # Auth failure → refresh token and retry once (safe for any method: 401 means nothing ran).
            if response.status_code == 401 and attempt == 0:
                try:
                    self.refresh_access_token()
                except Exception as exc:
                    raise GitHubIntegrationError(
                        f"GitHubIntegration: token refresh after 401 failed on {path}"
                    ) from exc
                continue
            # Rate limit → bubble up with retry hints (no in-method retry; the caller owns backoff).
            raise_if_github_rate_limited(response)
            if retry_transient and response.status_code in transient_status_codes and attempt == 0:
                logger.info(
                    "GitHubIntegration: api_request retrying transient error",
                    path=path,
                    status_code=response.status_code,
                )
                continue
            return response
        raise GitHubIntegrationError(f"GitHubIntegration: api_request exhausted retries on {path}")

    def _gh_api_get(self, path: str, *, endpoint: str, timeout: int = 10) -> dict:
        """Authenticated GET against ``https://api.github.com`` returning parsed JSON.

        Dict-or-raise sugar over :meth:`api_request`: any non-2xx (or non-dict body) becomes a
        :class:`GitHubIntegrationError`; rate limits propagate as :class:`GitHubRateLimitError`."""
        response = self.api_request("GET", path, endpoint=endpoint, timeout=timeout)
        if response.status_code < 200 or response.status_code >= 300:
            logger.warning(
                "GitHubIntegration: _gh_api_get non-2xx response",
                path=path,
                status_code=response.status_code,
            )
            raise GitHubIntegrationError(
                f"GitHubIntegration: _gh_api_get failed on {path}",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except Exception as exc:
            raise GitHubIntegrationError(
                f"GitHubIntegration: _gh_api_get non-JSON response on {path}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(body, dict):
            raise GitHubIntegrationError(
                f"GitHubIntegration: _gh_api_get unexpected payload on {path}",
                status_code=response.status_code,
            )
        return body

    @database_sync_to_async_pool
    def list_all_cached_repositories_async(self, max_repos: int | None = None) -> list[dict]:
        return self.list_all_cached_repositories(max_repos=max_repos)
