"""GitHub repositories attached to business knowledge.

The allowlist lives on this environment. Search reads the cached file tree and README.
File reads go to GitHub for one path that is already in that tree.
"""

from __future__ import annotations

import re
import json
import dataclasses
from datetime import timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.core.cache import cache
from django.db import connection, models, transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.event_usage import report_user_action
from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models.github_integration_base import GitHubIntegrationError, _is_safe_github_repo_path
from posthog.models.integration import GitHubIntegration
from posthog.models.integration_repository_cache import (
    GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS,
    GitHubRepositoryFullCache,
    IntegrationRepositoryCacheEntry,
)
from posthog.models.team.team import Team
from posthog.models.user import User

from .learning_settings import get_environment_business_knowledge_config
from .models import TeamBusinessKnowledgeConfig

logger = structlog.get_logger(__name__)

MAX_GITHUB_REPOS = 100
MAX_SEARCH_HITS = 20
MAX_README_HITS = 5
MAX_FILE_TEXT_CHARS = 32_000
README_EXCERPT_CHARS = 240
WARM_DEBOUNCE_SECONDS = 10 * 60
MAX_SEARCH_TERMS = 8

_TERM_RE = re.compile(r"[A-Za-z0-9_./-]{2,64}")
_STOP_TERMS = frozenset(
    {
        "a",
        "an",
        "and",
        "do",
        "does",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "or",
        "our",
        "the",
        "this",
        "to",
        "what",
    }
)


class GithubReposError(Exception):
    """User-safe failure. The message is shown to the caller."""


class RepositoryHitKind(models.TextChoices):
    PATH = "path", "Path"
    README = "readme", "Readme"


class RepositoryCacheStatus(models.TextChoices):
    READY = "ready", "Ready"
    WARMING = "warming", "Warming"


@frozen
class RepositorySearchHit:
    repo: str
    path: str
    url: str
    kind: str
    excerpt: str


@frozen
class RepositoryCacheState:
    repo: str
    tree_truncated: bool
    cache_status: str
    description: str


@frozen
class RepositorySearchOutcome:
    hits: list[RepositorySearchHit]
    repositories: list[RepositoryCacheState]


@frozen
class RepositoryFile:
    repo: str
    path: str
    url: str
    content: str
    truncated: bool


def repository_tools_enabled(team: Team) -> bool:
    integration_id, repos = selected_repositories(team)
    return integration_id is not None and bool(repos)


def selected_repositories(team: Team) -> tuple[int | None, list[str]]:
    config = (
        TeamBusinessKnowledgeConfig.objects.filter(team_id=team.id)
        .only("github_integration_id", "github_repos")
        .first()
    )
    if config is None or config.github_integration_id is None:
        return None, []
    return config.github_integration_id, _repo_names(config.github_repos)


def connection_status(team: Team) -> dict[str, Any]:
    config = TeamBusinessKnowledgeConfig.objects.filter(team_id=team.id).first()
    integration_id = config.github_integration_id if config is not None else None
    repos = _repo_names(config.github_repos) if config is not None else []
    integration = _integration_for(team.id, integration_id) if integration_id is not None else None
    if integration is None:
        return {"connected": False, "integration_id": None, "integration_name": "", "repos": []}
    account = integration.config.get("account", {}) if isinstance(integration.config, dict) else {}
    name = account.get("name", "") if isinstance(account, dict) else ""
    return {
        "connected": True,
        "integration_id": integration.id,
        "integration_name": name if isinstance(name, str) else "",
        "repos": repos,
    }


def connect_github(team: Team, integration_id: int) -> dict[str, Any]:
    integration = _integration_for(team.id, integration_id)
    if integration is None:
        raise GithubReposError("GitHub installation not found on this project.")
    config = get_environment_business_knowledge_config(team)
    if config.github_integration_id != integration.id:
        config.github_repos = []
    config.github_integration_id = integration.id
    _save_allowlist(team, config, ["github_integration_id", "github_repos"])
    return connection_status(team)


def disconnect_github(team: Team) -> dict[str, Any]:
    config = TeamBusinessKnowledgeConfig.objects.filter(team_id=team.id).first()
    if config is not None:
        config.github_integration_id = None
        config.github_repos = []
    _save_allowlist(team, config, ["github_integration_id", "github_repos"])
    return connection_status(team)


def select_github_repos(team: Team, repos: list[str]) -> dict[str, Any]:
    config = get_environment_business_knowledge_config(team)
    if config.github_integration_id is None or _integration_for(team.id, config.github_integration_id) is None:
        raise GithubReposError("Connect GitHub before choosing repositories.")
    validated = _validate_against_installation(team.id, config.github_integration_id, repos)
    config.github_repos = validated
    _save_allowlist(team, config, ["github_repos"])
    integration_id = config.github_integration_id

    def enqueue() -> None:
        for full_name in validated:
            enqueue_repository_warm(team.id, integration_id, full_name, force=True)

    transaction.on_commit(enqueue)
    return connection_status(team)


def search_repositories(
    team: Team,
    user: User,
    query: str,
    repo: str | None,
    library_id: UUID | None = None,
) -> RepositorySearchOutcome:
    integration, allowed = _require_allowlist(team)
    allowed = _restrict_to_library(team, allowed, library_id, repo)
    if not allowed:
        outcome = RepositorySearchOutcome(hits=[], repositories=[])
        _capture_tool(
            team, user, "search", 0, [], result_chars=_serialized_chars(outcome), library_scoped=library_id is not None
        )
        return outcome
    targets = _targets(allowed, repo)
    terms = search_terms(query)
    if not terms:
        raise GithubReposError("Pass file names or identifiers, not a whole sentence.")
    states = _cache_states(team.id, integration.id, targets)
    hits = _search_paths(team.id, integration.id, targets, terms)
    hits.extend(_search_readmes(team.id, integration.id, targets, terms))
    outcome = RepositorySearchOutcome(hits=hits, repositories=states)
    _capture_tool(
        team,
        user,
        "search",
        len(hits),
        states,
        result_chars=_serialized_chars(outcome),
        library_scoped=library_id is not None,
    )
    return outcome


def read_repository_file(
    team: Team, user: User, repo: str, path: str, library_id: UUID | None = None
) -> RepositoryFile:
    integration, allowed = _require_allowlist(team)
    full_name = repo.lower()
    allowed = _restrict_to_library(team, allowed, library_id, full_name)
    if full_name not in allowed:
        raise GithubReposError("That repository is not selected for business knowledge.")
    safe_path = _safe_blob_path(path)
    if safe_path is None:
        raise GithubReposError("That path is not a file in the cached tree.")
    sha = _sha_for_path(team.id, integration.id, full_name, safe_path)
    states = _cache_states(team.id, integration.id, [full_name])
    try:
        if sha is None:
            raise GithubReposError("That path is not a file in the cached tree.")
        loaded = _fetch_file(team, integration, full_name, safe_path, sha)
    except GithubReposError:
        _capture_tool(team, user, "file", 0, states, result_chars=0, library_scoped=library_id is not None)
        raise
    _capture_tool(
        team, user, "file", 1, states, result_chars=_serialized_chars(loaded), library_scoped=library_id is not None
    )
    return loaded


def _fetch_file(team: Team, integration: IntegrationRecord, full_name: str, path: str, sha: str) -> RepositoryFile:
    try:
        payload = GitHubIntegration(
            integration, source="business_knowledge", priority=Priority.NORMAL
        ).get_file_contents(full_name, _quote_github_path(path), ref=sha)
    except UnicodeDecodeError:
        raise GithubReposError("That file is not text.")
    except (GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted):
        logger.warning("business_knowledge.github_file_read_failed", team_id=team.id, repo=full_name)
        raise GithubReposError("Couldn't read that file. Try again.")
    if payload is None:
        raise GithubReposError("That file is not in the repository anymore. Search again.")
    content = payload.get("content")
    if not isinstance(content, str):
        raise GithubReposError("Couldn't read that file. Try again.")
    truncated = len(content) > MAX_FILE_TEXT_CHARS
    if truncated:
        content = content[:MAX_FILE_TEXT_CHARS]
    return RepositoryFile(
        repo=full_name,
        path=path,
        url=_blob_url(full_name, sha, path),
        content=content,
        truncated=truncated,
    )


def warm_selected_repository(team_id: int, integration_id: int, full_name: str) -> None:
    """Refresh one allowlisted repo. No-ops when the selection changed before the task ran."""
    config = (
        TeamBusinessKnowledgeConfig.objects.filter(team_id=team_id)
        .only("github_integration_id", "github_repos")
        .first()
    )
    if config is None or config.github_integration_id != integration_id:
        return
    if full_name not in _repo_names(config.github_repos):
        return
    integration = _integration_for(team_id, integration_id)
    if integration is None:
        return
    github = GitHubIntegration(integration, source="business_knowledge", priority=Priority.BATCH)
    try:
        async_to_sync(GitHubRepositoryFullCache(github, priority=Priority.BATCH).sync_full_cache_entry_async)(full_name)
    except GitHubIntegrationError as exc:
        # GitHub answers 404 when the repository left the installation. Drop the cached tree and README
        # so search cannot return them. The selection stays, so access comes back if the repo is re-added.
        if exc.status_code != 404:
            raise
        IntegrationRepositoryCacheEntry.objects.filter(
            team_id=team_id, integration_id=integration_id, full_name=full_name
        ).delete()
        logger.info("business_knowledge.github_repo_evicted", team_id=team_id, repo=full_name)


def enqueue_repository_warm(team_id: int, integration_id: int, full_name: str, *, force: bool) -> bool:
    """Return True when a warm task was queued. Search debounces; an explicit save does not."""
    from .tasks.tasks import warm_business_knowledge_github_repo  # noqa: PLC0415 — tasks.tasks imports this module

    key = f"business_knowledge:github_warm:{team_id}:{full_name}"
    if not force and not cache.add(key, "1", timeout=WARM_DEBOUNCE_SECONDS):
        return False
    try:
        warm_business_knowledge_github_repo.delay(team_id, integration_id, full_name)
    except Exception:
        # Release the debounce key so the next search retries the warm instead of waiting it out.
        cache.delete(key)
        logger.warning("business_knowledge.github_warm_enqueue_failed", team_id=team_id, repo=full_name, exc_info=True)
        return False
    if force:
        cache.set(key, "1", timeout=WARM_DEBOUNCE_SECONDS)
    return True


def search_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in _TERM_RE.findall(query):
        term = match.lower()
        if term in _STOP_TERMS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) == MAX_SEARCH_TERMS:
            break
    return terms


def _require_allowlist(team: Team) -> tuple[IntegrationRecord, list[str]]:
    integration_id, allowed = selected_repositories(team)
    if integration_id is None or not allowed:
        raise GithubReposError("No GitHub repositories are selected for business knowledge.")
    integration = _integration_for(team.id, integration_id)
    if integration is None:
        raise GithubReposError("GitHub installation not found on this project.")
    accessible = _installation_repo_names(integration)
    allowed = [full_name for full_name in allowed if full_name in accessible]
    if not allowed:
        raise GithubReposError("The selected repositories are no longer on this GitHub installation.")
    return integration, allowed


def _installation_repo_names(integration: IntegrationRecord) -> set[str]:
    # A pure read of the stored repository list, so a repository removed from the installation
    # stops being searchable as soon as that list refreshes, even while its cache row remains.
    listed = GitHubIntegration(
        integration, source="business_knowledge", priority=Priority.NORMAL
    ).list_all_cached_repositories(allow_refresh=False)
    return {
        item["full_name"].lower()
        for item in listed
        if isinstance(item, dict) and isinstance(item.get("full_name"), str)
    }


def _restrict_to_library(team: Team, allowed: list[str], library_id: UUID | None, repo: str | None) -> list[str]:
    """Intersect the allowlist with a library. An empty result means search should return no hits."""
    if library_id is None:
        return allowed
    from .libraries import LibraryNotFound, library_repo_names  # noqa: PLC0415 — libraries imports this module's models

    try:
        members = library_repo_names(team.id, library_id)
    except LibraryNotFound:
        raise GithubReposError("That library was not found.") from None
    if repo:
        full_name = repo.lower()
        if full_name not in members:
            raise GithubReposError("That repository is not selected for business knowledge.")
    return [full_name for full_name in allowed if full_name in members]


def _save_allowlist(team: Team, config: TeamBusinessKnowledgeConfig | None, update_fields: list[str]) -> None:
    from .libraries import (  # noqa: PLC0415 — libraries is not on the import path
        lock_libraries,
        project_allowed_repos,
        prune_repository_links,
    )

    # Environments of a project share library links. Without one lock, a prune can read another environment's
    # allowlist before that environment saves it and delete links the new allowlist keeps.
    with transaction.atomic():
        lock_libraries(team.id)
        if config is not None:
            config.save(update_fields=update_fields)
        prune_repository_links(team.id, project_allowed_repos(team))


def _targets(allowed: list[str], repo: str | None) -> list[str]:
    if repo is None or repo == "":
        return allowed
    full_name = repo.lower()
    if full_name not in allowed:
        raise GithubReposError("That repository is not selected for business knowledge.")
    return [full_name]


def _validate_against_installation(team_id: int, integration_id: int, repos: list[str]) -> list[str]:
    if len(repos) > MAX_GITHUB_REPOS:
        raise GithubReposError(f"Choose at most {MAX_GITHUB_REPOS} repositories.")
    integration = _integration_for(team_id, integration_id)
    if integration is None:
        raise GithubReposError("GitHub installation not found on this project.")
    github = GitHubIntegration(integration, source="business_knowledge", priority=Priority.NORMAL)
    try:
        listed = github.list_all_cached_repositories()
    # Without a cached snapshot the refresh re-raises whatever the sync hit, not only GitHub errors.
    except Exception:
        logger.warning("business_knowledge.github_repo_list_failed", team_id=team_id, exc_info=True)
        raise GithubReposError("Couldn't load repositories from GitHub. Try again.")
    available = {
        item["full_name"].lower()
        for item in listed
        if isinstance(item, dict) and isinstance(item.get("full_name"), str)
    }
    validated: list[str] = []
    seen: set[str] = set()
    for repo in repos:
        if not isinstance(repo, str) or not _is_safe_github_repo_path(repo):
            raise GithubReposError("Repository names must look like owner/repo.")
        lowered = repo.lower()
        if lowered not in available:
            raise GithubReposError(f"{repo} is not available on this GitHub installation.")
        if lowered not in seen:
            seen.add(lowered)
            validated.append(lowered)
    return validated


def _cache_states(team_id: int, integration_id: int, repos: list[str]) -> list[RepositoryCacheState]:
    rows = {
        row.full_name: row
        for row in IntegrationRepositoryCacheEntry.objects.filter(
            team_id=team_id, integration_id=integration_id, full_name__in=repos
        ).only("full_name", "updated_at", "tree_truncated", "default_branch_sha", "description")
    }
    fresh_after = timezone.now() - timedelta(seconds=GITHUB_REPOSITORY_FULL_CACHE_TTL_SECONDS)
    states: list[RepositoryCacheState] = []
    for full_name in repos:
        row = rows.get(full_name)
        fresh = row is not None and bool(row.default_branch_sha) and row.updated_at >= fresh_after
        if not fresh:
            enqueue_repository_warm(team_id, integration_id, full_name, force=False)
        states.append(
            RepositoryCacheState(
                repo=full_name,
                tree_truncated=bool(row.tree_truncated) if row is not None else False,
                cache_status=RepositoryCacheStatus.READY if fresh else RepositoryCacheStatus.WARMING,
                description=row.description if row is not None and isinstance(row.description, str) else "",
            )
        )
    return states


def _search_paths(team_id: int, integration_id: int, repos: list[str], terms: list[str]) -> list[RepositorySearchHit]:
    # tree_paths is the whole default-branch file list, several MB on a large repo.
    # Match in Postgres so that text never crosses into the worker.
    # The tree_paths prefilter skips the unnest for a repository with no matching path, so only
    # repositories that can produce a hit expand into one row per file.
    table = IntegrationRepositoryCacheEntry._meta.db_table
    patterns = [_ilike_pattern(term) for term in terms]
    score = " + ".join(["(CASE WHEN path ILIKE %s ESCAPE '\\' THEN 1 ELSE 0 END)"] * len(patterns))
    matched = " OR ".join(["path ILIKE %s ESCAPE '\\'"] * len(patterns))
    tree_matched = " OR ".join(["e.tree_paths ILIKE %s ESCAPE '\\'"] * len(patterns))
    repo_placeholders = ", ".join(["%s"] * len(repos))
    sql = f"""
        SELECT full_name, path, default_branch_sha, ({score}) AS score
        FROM (
            SELECT e.full_name, u.path AS path, e.default_branch_sha
            FROM {table} e
            CROSS JOIN LATERAL unnest(string_to_array(e.tree_paths, chr(10))) AS u(path)
            WHERE e.team_id = %s
              AND e.integration_id = %s
              AND e.full_name IN ({repo_placeholders})
              AND ({tree_matched})
              AND u.path <> ''
        ) paths
        WHERE {matched}
        ORDER BY score DESC, length(path), full_name, path
        LIMIT %s
    """
    params: list[Any] = [*patterns, team_id, integration_id, *repos, *patterns, *patterns, MAX_SEARCH_HITS]
    hits: list[RepositorySearchHit] = []
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        for full_name, path, sha, _score in cursor.fetchall():
            if not isinstance(full_name, str) or not isinstance(path, str) or not isinstance(sha, str):
                continue
            hits.append(
                RepositorySearchHit(
                    repo=full_name,
                    path=path,
                    url=_blob_url(full_name, sha, path),
                    kind=RepositoryHitKind.PATH,
                    excerpt="",
                )
            )
    return hits


def _search_readmes(team_id: int, integration_id: int, repos: list[str], terms: list[str]) -> list[RepositorySearchHit]:
    table = IntegrationRepositoryCacheEntry._meta.db_table
    patterns = [_ilike_pattern(term) for term in terms]
    matched = " OR ".join(["readme ILIKE %s ESCAPE '\\'"] * len(patterns))
    repo_placeholders = ", ".join(["%s"] * len(repos))
    sql = f"""
        SELECT full_name, default_branch_sha, readme
        FROM {table}
        WHERE team_id = %s
          AND integration_id = %s
          AND full_name IN ({repo_placeholders})
          AND ({matched})
        LIMIT %s
    """
    params: list[Any] = [team_id, integration_id, *repos, *patterns, MAX_README_HITS]
    hits: list[RepositorySearchHit] = []
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        for full_name, sha, readme in cursor.fetchall():
            if not isinstance(full_name, str) or not isinstance(sha, str) or not isinstance(readme, str):
                continue
            hits.append(
                RepositorySearchHit(
                    repo=full_name,
                    path="",
                    url=f"https://github.com/{full_name}/tree/{sha}#readme",
                    kind=RepositoryHitKind.README,
                    excerpt=_excerpt(readme, terms),
                )
            )
    return hits


def _sha_for_path(team_id: int, integration_id: int, full_name: str, path: str) -> str | None:
    table = IntegrationRepositoryCacheEntry._meta.db_table
    sql = f"""
        SELECT default_branch_sha
        FROM {table}
        WHERE team_id = %s
          AND integration_id = %s
          AND full_name = %s
          AND strpos(chr(10) || tree_paths || chr(10), chr(10) || %s || chr(10)) > 0
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [team_id, integration_id, full_name, path])
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], str) or not row[0]:
        return None
    return row[0]


def _safe_blob_path(path: str) -> str | None:
    if not path or path.startswith("/") or "\\" in path or "\n" in path or "\x00" in path:
        return None
    segments = path.split("/")
    if any(segment in ("", ".", "..") or "?" in segment or "#" in segment for segment in segments):
        return None
    return path


def _quote_github_path(path: str) -> str:
    return "/".join(quote(segment, safe="") for segment in path.split("/"))


def _blob_url(full_name: str, sha: str, path: str) -> str:
    return f"https://github.com/{full_name}/blob/{sha}/{_quote_github_path(path)}"


def _excerpt(readme: str, terms: list[str]) -> str:
    lower = readme.lower()
    index = 0
    for term in terms:
        found = lower.find(term)
        if found >= 0:
            index = found
            break
    start = max(0, index - 80)
    return " ".join(readme[start : start + README_EXCERPT_CHARS].split())


def _ilike_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _integration_for(team_id: int, integration_id: int | None) -> IntegrationRecord | None:
    if integration_id is None:
        return None
    try:
        return IntegrationManager.github.oauth.get(team_id, integration_id)
    except IntegrationNotFound:
        return None


def _repo_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _serialized_chars(result: RepositorySearchOutcome | RepositoryFile) -> int:
    return len(json.dumps(dataclasses.asdict(result)))


def _capture_tool(
    team: Team,
    user: User,
    tool: str,
    result_count: int,
    states: list[RepositoryCacheState],
    *,
    result_chars: int,
    library_scoped: bool = False,
) -> None:
    cache_status = (
        RepositoryCacheStatus.WARMING
        if any(state.cache_status == RepositoryCacheStatus.WARMING for state in states)
        else RepositoryCacheStatus.READY
    )
    try:
        report_user_action(
            user,
            "business knowledge repo tool called",
            {
                "tool": tool,
                "result_count": result_count,
                "cache_status": str(cache_status),
                "library_scoped": library_scoped,
                # The tools call no model. Their cost is the text they add to the calling agent's context.
                "result_chars": result_chars,
            },
            team=team,
        )
    except Exception:
        logger.warning("business_knowledge.github_tool_capture_failed", team_id=team.id, tool=tool)
