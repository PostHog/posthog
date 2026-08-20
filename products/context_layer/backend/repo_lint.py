#!/usr/bin/env python3
"""Structure linter for a context layer wiki checkout.

Deliberately stdlib-only and dependency-free: the scaffolder copies this file
verbatim into every wiki as `scripts/lint`, so agents run the exact rules the
server enforces at land time. Keep it runnable as a standalone script.
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

ALLOWED_ROOT_FILES = {"AGENTS.md", "CLAUDE.md"}
ALLOWED_DIRECTORIES = {"org", "areas", "decisions", "channels", "scripts"}
MARKDOWN_DIRECTORIES = {"org", "areas", "decisions", "channels"}
# Pages are prose; anything near this size is a dump of raw data, not a wiki page.
MAX_FILE_BYTES = 1_000_000
# Aggregate bounds keep a whole wiki readable in one pass: reads warm every page
# from a single checkout, so the repository must stay far below worker memory.
MAX_TOTAL_BYTES = 50_000_000
MAX_FILE_COUNT = 2_000
DECISION_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.md$")
FRONTMATTER_DELIMITER = "---"
# `[[page]]` wikilinks are the graph between pages. A target may carry an
# Obsidian-style `|display` suffix, which names the same page.
WIKILINK_RE = re.compile(r"\[\[([^\]\[]+?)\]\]")


def lint_repo(root: Path | str, *, pin_scripts: bool = True) -> list[str]:
    """Return every structure violation in the checkout at `root`, empty when clean.

    `pin_scripts=False` skips the script-content comparison; use it when linting
    historical trees, which legitimately carry earlier script versions. The tree
    that actually lands (and gets executed by agents) must keep the default.
    Only hard errors are returned here; advisory findings (orphan pages) are
    surfaced separately by `lint_repo_with_warnings` and never block a landing.
    """
    errors, _ = lint_repo_with_warnings(root, pin_scripts=pin_scripts)
    return errors


def lint_repo_with_warnings(root: Path | str, *, pin_scripts: bool = True) -> tuple[list[str], list[str]]:
    """Structure violations as (errors, warnings).

    Errors block a landing; warnings (currently orphan pages) are advisory —
    they keep the wiki tidy but never fail the land, because a page can be
    legitimately unlinked while it is being written.
    """
    root = Path(root)
    errors: list[str] = []
    warnings: list[str] = []

    agents_md = root / "AGENTS.md"
    if not agents_md.is_file() or agents_md.is_symlink():
        errors.append("AGENTS.md must exist at the repo root as a regular file")

    claude_md = root / "CLAUDE.md"
    if not claude_md.is_symlink() or claude_md.resolve() != agents_md.resolve():
        errors.append("CLAUDE.md must be a symlink to AGENTS.md")

    for entry in sorted(root.iterdir()):
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            if entry.name not in ALLOWED_DIRECTORIES:
                errors.append(f"{entry.name}/: only {', '.join(sorted(ALLOWED_DIRECTORIES))} are allowed at the root")
            continue
        if entry.name not in ALLOWED_ROOT_FILES:
            errors.append(f"{entry.name}: only AGENTS.md and CLAUDE.md are allowed as root files")

    for directory in sorted(MARKDOWN_DIRECTORIES):
        errors.extend(_lint_markdown_directory(root, directory))
    errors.extend(_lint_channel_ids(root))
    warnings.extend(_lint_orphan_pages(root))

    errors.extend(_lint_scripts_directory(root, pin_scripts=pin_scripts))

    total_bytes = 0
    file_count = 0
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        total_bytes += path.stat().st_size
        file_count += 1
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{path.relative_to(root)}: exceeds the {MAX_FILE_BYTES // 1_000_000} MB page size limit")
        elif path.suffix == ".md":
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"{path.relative_to(root)}: pages must be UTF-8 encoded")

    if total_bytes > MAX_TOTAL_BYTES:
        errors.append(f"the wiki exceeds the {MAX_TOTAL_BYTES // 1_000_000} MB total size limit")
    if file_count > MAX_FILE_COUNT:
        errors.append(f"the wiki exceeds the {MAX_FILE_COUNT} file limit")

    return errors, warnings


def _lint_markdown_directory(root: Path, directory: str) -> list[str]:
    base = root / directory
    if not base.is_dir():
        return []

    errors: list[str] = []
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            errors.append(f"{relative}: symlinks are only allowed for the root CLAUDE.md")
            continue
        if path.is_dir():
            continue
        if path.suffix != ".md":
            errors.append(f"{relative}: only Markdown pages are allowed under {directory}/")
            continue
        if directory == "decisions" and not DECISION_FILE_RE.fullmatch(path.name):
            errors.append(f"{relative}: decision pages must be named <YYYY-MM-DD>-<slug>.md")
        if directory == "channels" and not _frontmatter(path).get("channel_id"):
            errors.append(f"{relative}: channel pages need a non-empty `channel_id` in their frontmatter")
    return errors


def _lint_channel_ids(root: Path) -> list[str]:
    channels = root / "channels"
    if not channels.is_dir():
        return []
    errors: list[str] = []
    paths_by_id: dict[str, list[Path]] = {}
    for path in sorted(channels.rglob("*.md")):
        channel_id = _frontmatter(path).get("channel_id")
        if not channel_id:
            continue
        try:
            parsed = uuid.UUID(channel_id)
        except ValueError:
            errors.append(f"{path.relative_to(root)}: `channel_id` must be a UUID")
            continue
        # Resolution looks the page up by the channel's canonical UUID string, so a
        # non-canonical spelling (uppercase, braces, urn: prefix, unhyphenated) would
        # land clean yet never match its own channel — and slip past the uniqueness
        # check below, which keys on the raw text. Require the canonical form instead.
        if channel_id != str(parsed):
            errors.append(f"{path.relative_to(root)}: `channel_id` must be the canonical UUID form `{parsed}`")
            continue
        paths_by_id.setdefault(channel_id, []).append(path)
    for channel_id, paths in paths_by_id.items():
        if len(paths) > 1:
            joined_paths = ", ".join(str(path.relative_to(root)) for path in paths)
            errors.append(f"channel_id {channel_id} appears in more than one page: {joined_paths}")
    return errors


PUBLISH_SCRIPT = """\
#!/bin/sh
# Land local wiki commits: pack them as a git bundle and post them to the
# context layer API, which lints them and rebases them onto the current head.
# A dream/<YYYY-MM-DD> branch lands as one merge commit instead.
set -eu
cd "$(dirname "$0")/.."
if [ -z "${POSTHOG_API_URL:-}" ] || [ -z "${POSTHOG_PERSONAL_API_KEY:-}" ] || [ -z "${POSTHOG_CONTEXT_LAYER_COMMITS_PATH:-}" ]; then
    echo "publish: POSTHOG_API_URL, POSTHOG_PERSONAL_API_KEY, and POSTHOG_CONTEXT_LAYER_COMMITS_PATH must be set (they are inside PostHog sandboxes)" >&2
    exit 1
fi
branch="$(git rev-parse --abbrev-ref HEAD)"
if ! git bundle create /tmp/context-layer-publish.bundle "origin/main..$branch" 2>/dev/null; then
    echo "publish: nothing to publish; commit your edits first"
    exit 0
fi
if [ "$branch" = "main" ]; then
    curl -fsS -X POST \\
        -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
        -F "bundle=@/tmp/context-layer-publish.bundle" \\
        "${POSTHOG_API_URL%/}$POSTHOG_CONTEXT_LAYER_COMMITS_PATH"
else
    curl -fsS -X POST \\
        -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
        -F "bundle=@/tmp/context-layer-publish.bundle" \\
        -F "branch=$branch" \\
        "${POSTHOG_API_URL%/}$POSTHOG_CONTEXT_LAYER_COMMITS_PATH"
fi
echo ""
# The server rebases (or merges) the commits onto its current head, so the
# local refs are now behind the landed history. Re-publishing from here is
# safe (the rebase drops commits that reproduce already-landed changes), but
# the local log will not show the landed shas.
echo "publish: landed (the response's head_sha is the new wiki head; this clone's refs are now behind it)"
"""


def _canonical_scripts() -> dict[str, str]:
    """Byte-exact content each allowed script must carry.

    Agents are told to execute these scripts, so a tampered copy must never
    land: the server-side lint runs from PostHog's own module, making this
    comparison authoritative at land time. (Run as `scripts/lint` inside a
    wiki, the self-comparison is vacuous — the server check is the gate.)
    """
    return {"lint": Path(__file__).read_text(encoding="utf-8"), "publish": PUBLISH_SCRIPT}


def _lint_scripts_directory(root: Path, *, pin_scripts: bool = True) -> list[str]:
    base = root / "scripts"
    if not base.is_dir():
        return []

    canonical = _canonical_scripts()
    errors: list[str] = []
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            errors.append(f"{relative}: symlinks are only allowed for the root CLAUDE.md")
            continue
        if path.parent != base or not path.is_file() or path.name not in canonical:
            allowed = ", ".join(sorted(canonical))
            errors.append(f"{relative}: scripts/ may only contain {allowed}")
            continue
        if pin_scripts and path.read_text(encoding="utf-8", errors="replace") != canonical[path.name]:
            errors.append(f"{relative}: must match the script PostHog ships; restore it from a fresh clone")
    return errors


def _lint_orphan_pages(root: Path) -> list[str]:
    """Pages nothing links to are undiscoverable dead weight.

    Dangling outbound links stay legal: they mark a page worth writing. But a
    page with no inbound wikilink can never be reached by following the graph,
    so it rots unread. The map in AGENTS.md counts as an inbound link, so
    wiring a new hub page into the map (or into a hub page) is the fix.
    """
    pages: dict[str, Path] = {}
    for directory in MARKDOWN_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if path.is_symlink() or not path.is_file():
                continue
            pages[str(path.relative_to(root))[:-3]] = path

    if not pages:
        return []

    # outbound[file] = the wikilink targets that file points at. A page's own
    # links never count toward its inbound set, so a page that only links to
    # itself is still an orphan.
    outbound: dict[Path, set[str]] = {}
    for path in [root / "AGENTS.md", *pages.values()]:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        outbound[path] = {_normalize_link(match.group(1)) for match in WIKILINK_RE.finditer(content)}

    warnings: list[str] = []
    for target, path in sorted(pages.items()):
        linked = any(linker != path and (target in links or path.stem in links) for linker, links in outbound.items())
        if not linked:
            warnings.append(f"{path.relative_to(root)}: no page links to it; link it from a hub page or remove it")
    return warnings


def _normalize_link(link: str) -> str:
    return link.split("|", 1)[0].strip()


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_DELIMITER:
            return fields
        key, separator, value = line.partition(":")
        if separator and key == key.strip() and key.strip():
            fields[key.strip()] = value.strip()
    return {}


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    errors, warnings = lint_repo_with_warnings(root)
    for warning in warnings:
        print(f"warning: {warning}")  # noqa: T201
    for error in errors:
        print(error)  # noqa: T201
    if errors:
        print(f"{len(errors)} problem(s) found")  # noqa: T201
        return 1
    if warnings:
        print(f"{len(warnings)} warning(s) found; fix them to keep the wiki tidy")  # noqa: T201
    print("wiki structure OK")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
