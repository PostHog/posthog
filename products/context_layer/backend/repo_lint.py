#!/usr/bin/env python3
"""Structure linter for a context layer wiki checkout.

Deliberately stdlib-only and dependency-free: the scaffolder copies this file
verbatim into every wiki as `scripts/lint`, so agents run the exact rules the
server enforces at land time. Keep it runnable as a standalone script.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED_ROOT_FILES = {"AGENTS.md", "CLAUDE.md"}
ALLOWED_DIRECTORIES = {"org", "areas", "decisions", "channels", "scripts"}
MARKDOWN_DIRECTORIES = {"org", "areas", "decisions", "channels"}
# Pages are prose; anything near this size is a dump of raw data, not a wiki page.
MAX_FILE_BYTES = 1_000_000
DECISION_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.md$")
FRONTMATTER_DELIMITER = "---"


def lint_repo(root: Path | str) -> list[str]:
    """Return every structure violation in the checkout at `root`, empty when clean."""
    root = Path(root)
    errors: list[str] = []

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

    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{path.relative_to(root)}: exceeds the {MAX_FILE_BYTES // 1_000_000} MB page size limit")

    return errors


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
        if directory == "channels" and "channel_id" not in _frontmatter_keys(path):
            errors.append(f"{relative}: channel pages need `channel_id` in their frontmatter")
    return errors


def _frontmatter_keys(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return set()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return set()
    keys: set[str] = set()
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_DELIMITER:
            return keys
        key, separator, _ = line.partition(":")
        if separator and key == key.strip() and key.strip():
            keys.add(key.strip())
    return set()


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    errors = lint_repo(root)
    for error in errors:
        print(error)  # noqa: T201
    if errors:
        print(f"{len(errors)} problem(s) found")  # noqa: T201
        return 1
    print("wiki structure OK")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
