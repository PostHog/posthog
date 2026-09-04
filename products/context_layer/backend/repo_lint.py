#!/usr/bin/env python3
"""Structure linter for a context layer wiki checkout."""

from __future__ import annotations

import re
import sys
import uuid
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath

ALLOWED_ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "index.md"}
ALLOWED_DIRECTORIES = {"org", "areas", "decisions", "projects", "scripts"}
MARKDOWN_DIRECTORIES = {"org", "areas", "decisions", "projects"}
MAX_FILE_BYTES = 16_000
# Aggregate bounds keep a whole wiki readable in one pass: reads warm every page
# from a single checkout, so the repository must stay far below worker memory.
MAX_TOTAL_BYTES = 50_000_000
MAX_FILE_COUNT = 2_000
DECISION_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.md$")
WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
MALFORMED_WIKILINK_RE = re.compile(r"\[\[|\]\]")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
DISAGREEMENT_RE = re.compile(r"^.*\*\*Disagreement:\*\*.*$", re.MULTILINE)
FRONTMATTER_DELIMITER = "---"
ALLOWED_STATUSES = {"active", "superseded", "historical"}
REQUIRED_AGENTS_FRAGMENTS = (
    "## Admission test",
    "A fact enters the wiki only if it changes a durable fact, decision, priority, ownership, reusable definition, constraint, or an evidenced recurring pattern.",
    "External systems remain authoritative",
    "never edit `index.md`",
)


def _page_paths(root: Path) -> list[Path]:
    return [
        path
        for directory in MARKDOWN_DIRECTORIES
        for path in sorted((root / directory).rglob("*.md"))
        if path.is_file() and not path.is_symlink() and path.name != "index.md"
    ]


def _wikilink_target(raw_target: str) -> str | None:
    target = raw_target.split("|", 1)[0].split("#", 1)[0].strip().removesuffix(".md")
    path = PurePosixPath(target)
    if not target or path.is_absolute() or ".." in path.parts or target.startswith("."):
        return None
    return path.as_posix()


def lint_repo(root: Path | str, *, pin_scripts: bool = True) -> list[str]:
    root = Path(root)
    errors: list[str] = []
    agents_md = root / "AGENTS.md"
    if not agents_md.is_file() or agents_md.is_symlink():
        errors.append("AGENTS.md must exist at the repo root as a regular file")
    else:
        agents_text = agents_md.read_text(encoding="utf-8", errors="replace")
        for fragment in REQUIRED_AGENTS_FRAGMENTS:
            if fragment not in agents_text:
                errors.append(f"AGENTS.md: required guidance is missing: {fragment}")

    claude_md = root / "CLAUDE.md"
    if not claude_md.is_symlink() or claude_md.resolve() != agents_md.resolve():
        errors.append("CLAUDE.md must be a symlink to AGENTS.md")

    for entry in sorted(root.iterdir()):
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            if entry.name not in ALLOWED_DIRECTORIES:
                errors.append(f"{entry.name}/: only {', '.join(sorted(ALLOWED_DIRECTORIES))} are allowed at the root")
        elif entry.name not in ALLOWED_ROOT_FILES:
            errors.append(f"{entry.name}: only {', '.join(sorted(ALLOWED_ROOT_FILES))} are allowed as root files")
        elif entry.name != "CLAUDE.md" and entry.is_symlink():
            # The server rewrites index.md on every landing, so a symlinked root
            # file would let a bundle direct that write at an arbitrary path.
            errors.append(f"{entry.name}: root files other than CLAUDE.md must be regular files")

    titles: dict[str, Path] = {}
    for directory in sorted(MARKDOWN_DIRECTORIES):
        errors.extend(_lint_markdown_directory(root, directory, titles))
    errors.extend(_lint_channel_ids(root))
    errors.extend(_lint_scripts_directory(root, pin_scripts=pin_scripts))
    total_bytes = 0
    file_count = 0
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        total_bytes += path.stat().st_size
        file_count += 1
        if path.suffix == ".md":
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"{path.relative_to(root)}: pages must be UTF-8 encoded")
    if total_bytes > MAX_TOTAL_BYTES:
        errors.append(f"the wiki exceeds the {MAX_TOTAL_BYTES // 1_000_000} MB total size limit")
    if file_count > MAX_FILE_COUNT:
        errors.append(f"the wiki exceeds the {MAX_FILE_COUNT} file limit")
    return errors


def _lint_markdown_directory(root: Path, directory: str, titles: dict[str, Path]) -> list[str]:
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
        fields = _frontmatter(path)
        is_space_page = (
            directory == "projects"
            and len(relative.parts) == 4
            and relative.parts[2] == "spaces"
            and path.name != "index.md"
        )
        if is_space_page and not fields.get("channel_id"):
            errors.append(f"{relative}: Space pages need a non-empty `channel_id` in their frontmatter")
        if is_space_page and fields.get("team_id") != relative.parts[1]:
            errors.append(f"{relative}: Space pages need `team_id: {relative.parts[1]}` in their frontmatter")
        if path.name == "index.md":
            continue
        if not fields.get("summary") or "\n" in fields.get("summary", ""):
            errors.append(f"{relative}: frontmatter needs a one-line `summary`")
        status = fields.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{relative}: frontmatter `status` must be active, superseded, or historical")
        review_after = fields.get("review_after")
        if review_after:
            try:
                date.fromisoformat(review_after)
            except ValueError:
                errors.append(f"{relative}: frontmatter `review_after` must be an ISO date")
        if directory == "decisions" and not fields.get("sources"):
            errors.append(f"{relative}: decision pages need non-empty `sources` frontmatter")
        text = path.read_text(encoding="utf-8", errors="replace")
        links, malformed = _links(text)
        if malformed:
            errors.append(f"{relative}: contains a malformed or escaping wikilink")
        if status == "superseded" and not any((root / f"{target}.md").is_file() for target in links):
            errors.append(f"{relative}: superseded pages must wikilink an existing replacement")
        title_match = H1_RE.search(text)
        if title_match:
            normalized = re.sub(r"[^a-z0-9]+", " ", title_match.group(1).casefold()).strip()
            if normalized in titles:
                errors.append(f"{relative}: duplicates the normalized title in {titles[normalized].relative_to(root)}")
            else:
                titles[normalized] = path
    return errors


def _links(text: str) -> tuple[list[str], bool]:
    matches = list(WIKILINK_RE.finditer(text))
    targets = [_wikilink_target(match.group(1)) for match in matches]
    remainder = WIKILINK_RE.sub("", text)
    return [target for target in targets if target], any(target is None for target in targets) or bool(
        MALFORMED_WIKILINK_RE.search(remainder)
    )


def report_repo(root: Path | str) -> list[str]:
    root = Path(root)
    pages = _page_paths(root)
    targets_by_page: dict[Path, list[str]] = {}
    inbound: Counter[str] = Counter()
    for path in pages:
        targets, _ = _links(path.read_text(encoding="utf-8", errors="replace"))
        targets_by_page[path] = targets
        inbound.update(targets)
    findings: list[str] = []
    today = datetime.now(UTC).date()
    for path in pages:
        relative = path.relative_to(root).as_posix()
        target = relative.removesuffix(".md")
        fields = _frontmatter(path)
        age = _git_age(root, relative)
        if age is not None and age > timedelta(days=90):
            findings.append(f"stale: {relative}: last changed {age.days} days ago")
        review_after = fields.get("review_after")
        if fields.get("status") == "active" and review_after:
            try:
                if date.fromisoformat(review_after) < today:
                    findings.append(f"past_review: {relative}: review_after {review_after} has passed")
            except ValueError:
                pass
        if not inbound[target]:
            findings.append(f"orphan: {relative}: no page links here")
        if path.stat().st_size > MAX_FILE_BYTES:
            findings.append(f"oversized: {relative}: exceeds {MAX_FILE_BYTES // 1000} KB")
        if path.parts[-2] != "decisions" and not fields.get("sources"):
            findings.append(f"missing_sources: {relative}: no sources recorded")
        for marker in DISAGREEMENT_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
            findings.append(f"disagreement: {relative}: {marker.strip()}")
    existing = {path.relative_to(root).as_posix().removesuffix(".md") for path in pages}
    ghost_counts = Counter(
        target for targets in targets_by_page.values() for target in targets if target not in existing
    )
    for target, count in sorted(ghost_counts.items()):
        findings.append(f"ghost_link: {target}.md: referenced by {count} page(s)")
    return findings


def _git_age(root: Path, relative: str) -> timedelta | None:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", relative], cwd=root, capture_output=True, text=True, check=False
    )
    if not result.stdout.strip():
        return None
    changed = datetime.fromtimestamp(int(result.stdout.strip()), tz=UTC)
    return datetime.now(UTC) - changed


def _canonical_scripts() -> dict[str, str]:
    return {"lint": Path(__file__).read_text(encoding="utf-8"), "publish": PUBLISH_SCRIPT}


def _lint_channel_ids(root: Path) -> list[str]:
    channels = root / "projects"
    if not channels.is_dir():
        return []
    errors: list[str] = []
    paths_by_id: dict[str, list[Path]] = {}
    for path in sorted(channels.glob("*/spaces/*.md")):
        if path.name == "index.md":
            continue
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
summary_file="${1:-}"
set --
if [ -n "$summary_file" ]; then
    set -- "$@" -F "summary=@$summary_file"
fi
if [ "$branch" != "main" ]; then
    set -- "$@" -F "branch=$branch"
fi
curl -fsS -X POST \\
    -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
    -F "bundle=@/tmp/context-layer-publish.bundle" \\
    "$@" \\
    "${POSTHOG_API_URL%/}$POSTHOG_CONTEXT_LAYER_COMMITS_PATH"
echo ""
# The server rebases (or merges) the commits onto its current head, so the
# local refs are now behind the landed history. Re-publishing from here is
# safe (the rebase drops commits that reproduce already-landed changes), but
# the local log will not show the landed shas.
echo "publish: landed (the response's head_sha is the new wiki head; this clone's refs are now behind it)"
"""


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
        elif path.parent != base or not path.is_file() or path.name not in canonical:
            errors.append(f"{relative}: scripts/ may only contain {', '.join(sorted(canonical))}")
        elif pin_scripts and path.read_text(encoding="utf-8", errors="replace") != canonical[path.name]:
            errors.append(f"{relative}: must match the script PostHog ships; restore it from a fresh clone")
    return errors


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
    report = False
    args = argv[1:]
    if "--report" in args:
        report = True
        args.remove("--report")
    root = Path(args[0]) if args else Path.cwd()
    errors = lint_repo(root)
    for error in errors:
        print(error)  # noqa: T201
    if report:
        for finding in report_repo(root):
            print(finding)  # noqa: T201
    if errors:
        print(f"{len(errors)} problem(s) found")  # noqa: T201
        return 1
    print("wiki structure OK")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
