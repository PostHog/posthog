"""Read and write wiki pages without putting a bundle download on the request path.

Page contents are cached per head sha, so cache entries are immutable and need
no invalidation: a landed write moves the head, and the next read warms the new
sha's entries from one checkout.
"""

from __future__ import annotations

import uuid
import posixpath
from pathlib import Path

from posthog.dataclasses import frozen
from posthog.utils import get_safe_cache, safe_cache_set

from products.context_layer.backend import repo_lint, store

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


@frozen
class WikiTree:
    head_sha: str
    paths: list[str]


def _tree_cache_key(organization_id: uuid.UUID | str, head_sha: str) -> str:
    return f"context_layer:tree:{organization_id}:{head_sha}"


def _page_cache_key(organization_id: uuid.UUID | str, head_sha: str, path: str) -> str:
    return f"context_layer:page:{organization_id}:{head_sha}:{path}"


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
        head_sha, paths, _ = _warm_cache(organization_id)
    return WikiTree(head_sha=head_sha, paths=paths)


def get_page(organization_id: uuid.UUID | str, path: str) -> WikiPage:
    path = normalize_page_path(path)
    head_sha = store.get_config(organization_id).head_sha
    content = get_safe_cache(_page_cache_key(organization_id, head_sha, path))
    if content is None:
        # Answer misses from the cached tree when we can: repeated requests for
        # a nonexistent path must 404 cheaply, not re-download the bundle.
        known_paths = get_safe_cache(_tree_cache_key(organization_id, head_sha))
        if known_paths is not None and path not in known_paths:
            raise PageNotFoundError(f"no page at {path}")
        head_sha, _, pages = _warm_cache(organization_id)
        content = pages.get(path)
    if content is None:
        raise PageNotFoundError(f"no page at {path}")
    return WikiPage(path=path, content=content, head_sha=head_sha)


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


def _warm_cache(organization_id: uuid.UUID | str) -> tuple[str, list[str], dict[str, str]]:
    """One checkout warms the tree and every page for the checkout's head."""
    with store.checkout_repo(organization_id) as checkout:
        pages: dict[str, str] = {}
        for file_path in sorted(checkout.path.rglob("*.md")):
            if ".git" in file_path.parts or file_path.is_symlink() or not file_path.is_file():
                continue
            relative = str(file_path.relative_to(checkout.path))
            # The linter rejects non-UTF-8 pages at land time; replacement here
            # keeps one legacy file from turning every read into a 500.
            pages[relative] = file_path.read_text(encoding="utf-8", errors="replace")
        paths = sorted(pages)
        safe_cache_set(_tree_cache_key(organization_id, checkout.head_sha), paths, CACHE_TTL_SECONDS)
        for relative, content in pages.items():
            safe_cache_set(_page_cache_key(organization_id, checkout.head_sha, relative), content, CACHE_TTL_SECONDS)
        return checkout.head_sha, paths, pages
