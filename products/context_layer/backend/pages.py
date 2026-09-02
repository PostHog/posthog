"""Read and write wiki pages without putting a bundle download on the request path.

Page contents are cached per head sha, so cache entries are immutable and need
no invalidation: a landed write moves the head, and the next read warms the new
sha's entries from one checkout.
"""

from __future__ import annotations

import uuid
import posixpath
from datetime import UTC, datetime
from pathlib import Path

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.utils import get_safe_cache, safe_cache_set

from products.context_layer.backend import repo_lint, store
from products.context_layer.backend.enablement import _unique_channel_path
from products.tasks.backend.facade import api as tasks_facade

# Entries are keyed by head sha and therefore immutable; the TTL only bounds
# storage for heads nothing reads anymore.
CACHE_TTL_SECONDS = 24 * 60 * 60
PAGE_MAX_BYTES = 1_000_000


class PageNotFoundError(store.ContextLayerStoreError):
    pass


class InvalidPagePathError(store.ContextLayerStoreError):
    pass


@frozen
class WikiPage:
    path: str
    content: str
    head_sha: str
    updated_at: datetime


@frozen
class WikiTree:
    head_sha: str
    paths: list[str]


@frozen
class WikiHealthFinding:
    category: str
    path: str
    message: str


@frozen
class WikiHealthReport:
    head_sha: str
    findings: list[WikiHealthFinding]


def _tree_cache_key(organization_id: uuid.UUID | str, head_sha: str) -> str:
    return f"context_layer:tree:{organization_id}:{head_sha}"


def _page_cache_key(organization_id: uuid.UUID | str, head_sha: str, path: str) -> str:
    return f"context_layer:page:{organization_id}:{head_sha}:{path}"


def _report_cache_key(organization_id: uuid.UUID | str, head_sha: str) -> str:
    return f"context_layer:report:{organization_id}:{head_sha}:{datetime.now(UTC).date().isoformat()}"


def _channel_index_cache_key(organization_id: uuid.UUID | str, head_sha: str) -> str:
    return f"context_layer:channel-index:{organization_id}:{head_sha}"


def normalize_page_path(path: str) -> str:
    """Reject anything that could escape the checkout or point at a non-page.

    The structural rules come from `repo_lint` so a write into the wrong
    directory fails here, before paying for a checkout, and fails the same way
    the land-time lint would."""
    normalized = posixpath.normpath(path.strip().lstrip("/"))
    if (
        not normalized
        or normalized.startswith((".", "/"))
        or ".." in normalized.split("/")
        or not normalized.endswith(".md")
    ):
        raise InvalidPagePathError(f"{path!r} is not a wiki page path; expected a relative Markdown path")
    first_segment = normalized.split("/", 1)[0]
    # CLAUDE.md is deliberately not writable: it must stay a symlink to AGENTS.md.
    if normalized != "AGENTS.md" and first_segment not in repo_lint.MARKDOWN_DIRECTORIES:
        raise InvalidPagePathError(
            f"{path!r} is outside the wiki structure; pages live in "
            f"{', '.join(sorted(repo_lint.MARKDOWN_DIRECTORIES))} or at AGENTS.md"
        )
    return normalized


def get_tree(organization_id: uuid.UUID | str) -> WikiTree:
    """Every page path in the wiki at the current head."""
    head_sha = store.get_config(organization_id).head_sha
    paths = get_safe_cache(_tree_cache_key(organization_id, head_sha))
    if paths is None:
        # The head can move between the read above and the checkout; trust the
        # checkout's head so the returned sha always matches the returned paths.
        warmed = _warm_cache(organization_id)
        head_sha, paths = warmed.head_sha, warmed.paths
    return WikiTree(head_sha=head_sha, paths=paths)


def get_page(organization_id: uuid.UUID | str, path: str) -> WikiPage:
    path = normalize_page_path(path)
    head_sha = store.get_config(organization_id).head_sha
    cached = get_safe_cache(_page_cache_key(organization_id, head_sha, path))
    page = (
        WikiPage(
            path=path,
            content=cached["content"],
            head_sha=head_sha,
            updated_at=datetime.fromisoformat(cached["updated_at"]),
        )
        if isinstance(cached, dict) and "content" in cached and "updated_at" in cached
        else None
    )
    if page is None:
        # Answer misses from the cached tree when we can: repeated requests for
        # a nonexistent path must 404 cheaply, not re-download the bundle.
        known_paths = get_safe_cache(_tree_cache_key(organization_id, head_sha))
        if known_paths is not None and path not in known_paths:
            raise PageNotFoundError(f"no page at {path}")
        warmed = _warm_cache(organization_id)
        head_sha = warmed.head_sha
        page = warmed.pages.get(path)
    if page is None:
        raise PageNotFoundError(f"no page at {path}")
    return page


def get_health_report(organization_id: uuid.UUID | str) -> WikiHealthReport:
    head_sha = store.get_config(organization_id).head_sha
    cache_key = _report_cache_key(organization_id, head_sha)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return WikiHealthReport(
            head_sha=head_sha,
            findings=[WikiHealthFinding(**finding) for finding in cached],
        )
    with store.checkout_repo(organization_id) as checkout:
        findings = []
        for raw in repo_lint.report_repo(checkout.path):
            category, path, message = raw.split(": ", 2)
            findings.append(WikiHealthFinding(category=category, path=path, message=message))
        safe_cache_set(
            _report_cache_key(organization_id, checkout.head_sha),
            [{"category": finding.category, "path": finding.path, "message": finding.message} for finding in findings],
            CACHE_TTL_SECONDS,
        )
        return WikiHealthReport(head_sha=checkout.head_sha, findings=findings)


def resolve_channel_page(organization_id: uuid.UUID | str, channel_id: uuid.UUID | str) -> str | None:
    return _channel_index(organization_id).get(str(channel_id))


def resolve_page_channel(organization_id: uuid.UUID | str, path: str) -> str | None:
    """The channel a page belongs to, or None when the page isn't a channel page.

    The index only holds this organization's channels, so a channel id from
    another organization never resolves here.
    """
    path = normalize_page_path(path)
    for channel_id, page_path in _channel_index(organization_id).items():
        if page_path == path:
            return channel_id
    return None


def proposed_channel_page_path(organization_id: uuid.UUID | str, channel_id: uuid.UUID | str) -> str:
    """The canonical project-scoped path a channel's page would be created at.

    For channels created after wiki enablement, which the one-time import never
    saw. The slug is derived exactly like the import's, so a page created here
    lands where a re-import would have put it, and never collides with a page
    that already exists at the current head.
    """
    details = _channel_details(organization_id, channel_id)
    if details is None:
        raise PageNotFoundError(f"no channel {channel_id} in this organization")
    team_id, name = details
    taken = set(get_tree(organization_id).paths)
    path = _unique_channel_path(team_id, name, str(channel_id), taken)
    if path in taken:
        # Both the slug and its short-suffixed form belong to other channels'
        # pages; the full channel id is unique by construction.
        path = f"projects/{team_id}/spaces/{channel_id}.md"
    return path


def _channel_details(organization_id: uuid.UUID | str, channel_id: uuid.UUID | str) -> tuple[int, str] | None:
    """The project id and name of an organization's public channel, or None.

    Walks teams the same way enablement's import does: the channel-id lookup is
    org-wide, and the fail-closed channel models need an explicit team scope."""
    target = str(channel_id)
    for team_id in Team.objects.filter(organization_id=organization_id).order_by("id").values_list("id", flat=True):
        with team_scope(team_id):
            for channel in tasks_facade.list_channels(team_id, None):
                if str(channel.id) == target and channel.channel_type == "public":
                    return team_id, channel.name
    return None


def page_frontmatter_channel_id(content: str) -> str | None:
    """The `channel_id` a page's frontmatter declares, parsed the way resolution does."""
    return _frontmatter_value(content, "channel_id")


def _channel_index(organization_id: uuid.UUID | str) -> dict[str, str]:
    head_sha = store.get_config(organization_id).head_sha
    index = get_safe_cache(_channel_index_cache_key(organization_id, head_sha))
    if index is None:
        index = _warm_cache(organization_id).channel_paths
    return index


def write_page(
    organization_id: uuid.UUID | str,
    *,
    path: str,
    content: str,
    base_head: str | None = None,
    author: store.CommitAuthor | None = None,
) -> str:
    """Create or replace one page through the writer protocol; returns the new head."""
    path = normalize_page_path(path)
    if path.rsplit("/", 1)[-1] == "index.md":
        raise InvalidPagePathError("index pages are generated by the server and cannot be edited")
    if len(content.encode("utf-8")) > PAGE_MAX_BYTES:
        raise InvalidPagePathError(f"page content exceeds the {PAGE_MAX_BYTES // 1_000_000} MB limit")

    def mutate(root: Path) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return store.apply_changes(
        organization_id,
        message=f"Edit {path}",
        mutate=mutate,
        author=author,
        required_head=base_head,
    )


@frozen
class WarmedWiki:
    """One checkout's worth of readable state, keyed to the head it came from."""

    head_sha: str
    paths: list[str]
    pages: dict[str, WikiPage]
    channel_paths: dict[str, str]


def _warm_cache(organization_id: uuid.UUID | str) -> WarmedWiki:
    """One checkout warms the tree and every page for the checkout's head."""
    with store.checkout_repo(organization_id) as checkout:
        pages: dict[str, WikiPage] = {}
        channel_paths: dict[str, str] = {}
        for file_path in sorted(checkout.path.rglob("*.md")):
            if ".git" in file_path.parts or file_path.is_symlink() or not file_path.is_file():
                continue
            relative = str(file_path.relative_to(checkout.path))
            # The linter rejects non-UTF-8 pages at land time; replacement here
            # keeps one legacy file from turning every read into a 500.
            updated_at = store.get_path_updated_at(checkout, relative)
            pages[relative] = WikiPage(
                path=relative,
                content=file_path.read_text(encoding="utf-8", errors="replace"),
                head_sha=checkout.head_sha,
                updated_at=updated_at,
            )
            if relative.startswith("projects/") and "/spaces/" in relative and not relative.endswith("/index.md"):
                channel_id = _frontmatter_value(pages[relative].content, "channel_id")
                if channel_id:
                    channel_paths[channel_id] = relative
        paths = sorted(pages)
        safe_cache_set(_tree_cache_key(organization_id, checkout.head_sha), paths, CACHE_TTL_SECONDS)
        for relative, page in pages.items():
            safe_cache_set(
                _page_cache_key(organization_id, checkout.head_sha, relative),
                {"content": page.content, "updated_at": page.updated_at.isoformat()},
                CACHE_TTL_SECONDS,
            )
        safe_cache_set(_channel_index_cache_key(organization_id, checkout.head_sha), channel_paths, CACHE_TTL_SECONDS)
        return WarmedWiki(head_sha=checkout.head_sha, paths=paths, pages=pages, channel_paths=channel_paths)


def _frontmatter_value(content: str, key: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        name, separator, value = line.partition(":")
        if separator and name.strip() == key:
            return value.strip() or None
    return None
