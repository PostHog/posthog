#!/usr/bin/env python3
"""Structure linter for a context layer wiki checkout."""

from __future__ import annotations

import re
import sys
import json
import math
import uuid
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

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
KEY_VALUE_RE = re.compile(r"([A-Za-z_][\w-]*):(?: +(.*?))? *")
NUMBER_RE = re.compile(r"[-+]?(?:\.\d+|\d+(?:\.\d*)?)(?:[eE][-+]?\d+)?|0x[0-9a-fA-F]+|0o[0-7]+")
SINGLE_QUOTED_RE = re.compile(r"'((?:[^']|'')*)'")
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
        errors.extend(f"{relative}: {problem}" for problem in _lint_frontmatter_lists(_frontmatter_lines(path)))
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


Check = Callable[[object, str], list[str]]
Line = tuple[int, str]


class BlockSyntaxError(Exception):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")


class BlockParser:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = list(lines)
        self.pos = 0

    def parse(self) -> dict[str, object]:
        for number, text in self.lines:
            if text.strip() and "\t" in text[: len(text) - len(text.lstrip())]:
                raise BlockSyntaxError(number, "indent with spaces, not tabs")
        value = self._mapping(0)
        if (line := self._peek()) is not None:
            raise BlockSyntaxError(line[0], "unexpected content")
        return value

    def _peek(self) -> Line | None:
        while self.pos < len(self.lines):
            number, text = self.lines[self.pos]
            if text.strip() and not text.lstrip().startswith("#"):
                return number, text
            self.pos += 1
        return None

    @staticmethod
    def _indent(text: str) -> int:
        return len(text) - len(text.lstrip(" "))

    @staticmethod
    def _is_item(text: str, indent: int) -> bool:
        return text[indent:].startswith("- ")

    def _node(self, indent: int) -> object:
        line = self._peek()
        if line is None:
            return None
        number, text = line
        if self._indent(text) != indent:
            raise BlockSyntaxError(number, f"expected an indent of {indent} spaces, found {self._indent(text)}")
        if self._is_item(text, indent):
            return self._sequence(indent)
        if KEY_VALUE_RE.fullmatch(text[indent:]):
            return self._mapping(indent)
        self.pos += 1
        return self._scalar(text[indent:], indent, number)

    def _mapping(self, indent: int) -> dict[str, object]:
        result: dict[str, object] = {}
        while (line := self._peek()) is not None and self._indent(line[1]) == indent:
            number, text = line
            match = KEY_VALUE_RE.fullmatch(text[indent:])
            if match is None:
                raise BlockSyntaxError(number, "expected `key: value`")
            key, rest = match.group(1), match.group(2)
            if key in result:
                raise BlockSyntaxError(number, f"`{key}` appears twice")
            self.pos += 1
            result[key] = self._value(rest, indent, number)
        return result

    def _sequence(self, indent: int) -> list[object]:
        items: list[object] = []
        while (line := self._peek()) is not None and self._indent(line[1]) == indent and self._is_item(line[1], indent):
            number, text = line
            content = text[indent + 2 :]
            content_indent = indent + 2 + self._indent(content)
            self.lines[self.pos] = (number, " " * content_indent + content.lstrip(" "))
            items.append(self._node(content_indent))
        return items

    def _value(self, rest: str | None, indent: int, number: int) -> object:
        if not rest:
            return self._nested(indent)
        if rest in ("|", "|-"):
            return self._literal(indent, keep_newline=rest == "|")
        return self._scalar(rest, indent, number)

    def _nested(self, indent: int) -> object:
        line = self._peek()
        if line is None or self._indent(line[1]) < indent:
            return None
        if self._indent(line[1]) == indent:
            return self._sequence(indent) if self._is_item(line[1], indent) else None
        return self._node(self._indent(line[1]))

    def _literal(self, indent: int, *, keep_newline: bool) -> str:
        body: list[str] = []
        block_indent = 0
        while self.pos < len(self.lines):
            number, text = self.lines[self.pos]
            if text.strip():
                found = self._indent(text)
                if found <= indent:
                    break
                block_indent = block_indent or found
                if found < block_indent:
                    raise BlockSyntaxError(number, "literal block lines must be indented at least as far as the first")
            body.append(text[block_indent:] if text.strip() else "")
            self.pos += 1
        while body and body[-1] == "":
            body.pop()
        content = "\n".join(body)
        return content + "\n" if content and keep_newline else content

    def _scalar(self, text: str, indent: int, number: int) -> object:
        if text[0] in "|>":
            raise BlockSyntaxError(number, "multi-line text must be a literal block written as | or |-")
        following = self._peek()
        if following is not None and self._indent(following[1]) > indent:
            raise BlockSyntaxError(following[0], "text that spans lines must use a literal block (|)")
        if text[0] == '"':
            try:
                return str(json.loads(text))
            except ValueError:
                raise BlockSyntaxError(number, "malformed double-quoted text") from None
        if text[0] == "'":
            match = SINGLE_QUOTED_RE.fullmatch(text)
            if match is None:
                raise BlockSyntaxError(number, "malformed single-quoted text")
            return match.group(1).replace("''", "'")
        if text in ("[]", "{}"):
            return [] if text == "[]" else {}
        if text[0] in "[{":
            raise BlockSyntaxError(number, "write lists and mappings in block form, one entry per line")
        if text[0] in ",]}#&*!%@`" or text.startswith(("- ", "? ", ": ")):
            raise BlockSyntaxError(number, f"text cannot start with `{text[0]}`; quote it")
        plain = re.split(r"\s#", text, maxsplit=1)[0].rstrip()
        if ": " in plain or plain.endswith(":"):
            raise BlockSyntaxError(number, "text that contains a colon must be quoted")
        return _typed(plain)


def _typed(text: str) -> object:
    if text in {"true", "True", "TRUE"}:
        return True
    if text in {"false", "False", "FALSE"}:
        return False
    if text in {"null", "Null", "NULL", "~"}:
        return None
    if text.lstrip("+-").lower() in {".inf", ".nan"}:
        return float(text.replace(".", "", 1))
    if not NUMBER_RE.fullmatch(text):
        return text
    return int(text, 0) if text.startswith(("0x", "0o")) else float(text)


def _text(value: object, path: str) -> list[str]:
    return [] if isinstance(value, str) else [f"{path} must be text"]


def _flag(value: object, path: str) -> list[str]:
    return [] if isinstance(value, bool) else [f"{path} must be true or false"]


def _number(value: object, path: str) -> list[str]:
    numeric = isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    coercible = isinstance(value, str) and NUMBER_RE.fullmatch(value) is not None
    return [] if numeric or coercible else [f"{path} must be a number"]


def _iso_date(value: object, path: str) -> list[str]:
    try:
        well_formed = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        well_formed = False
    return [] if well_formed else [f"{path} must be a date written as YYYY-MM-DD"]


def _http_url(value: object, path: str) -> list[str]:
    parts = urlsplit(value) if isinstance(value, str) else None
    return [] if parts and parts.scheme in {"http", "https"} and parts.netloc else [f"{path} must be an http(s) URL"]


def _one_of(*options: str) -> Check:
    def check(value: object, path: str) -> list[str]:
        return [] if value in options else [f"{path} must be one of {', '.join(options)}"]

    return check


def _nullable(check: Check) -> Check:
    return lambda value, path: [] if value is None else check(value, path)


def _each(check: Check) -> Check:
    def check_all(value: object, path: str) -> list[str]:
        if not isinstance(value, list):
            return [f"{path} must be a list"]
        return [error for index, item in enumerate(value) for error in check(item, f"{path}[{index}]")]

    return check_all


def _mapping(required: dict[str, Check], optional: dict[str, Check] | None = None) -> Check:
    fields = {**required, **(optional or {})}

    def check(value: object, path: str) -> list[str]:
        if not isinstance(value, dict):
            return [f"{path} must be a mapping"]
        errors = [f"{path}.{key} is required" for key in required if key not in value]
        for key, item in value.items():
            field = fields.get(key)
            errors += field(item, f"{path}.{key}") if field else [f"{path}.{key} is not a known key"]
        return errors

    return check


def _tagged(tag: str, **variants: Check) -> Check:
    def check(value: object, path: str) -> list[str]:
        if not isinstance(value, dict):
            return [f"{path} must be a mapping"]
        variant = variants.get(str(value.get(tag)))
        if variant is None:
            return [f"{path}.{tag} must be one of {', '.join(variants)}"]
        return variant(value, path)

    return check


OBJECT_KINDS = (
    "insight",
    "dashboard",
    "flag",
    "experiment",
    "survey",
    "error",
    "replay",
    "notebook",
    "cohort",
    "action",
    "person",
    "event",
    "link",
)
TARGET = _mapping(
    {"direction": _one_of("at_least", "at_most"), "value": _number},
    {"due_date": _nullable(_iso_date)},
)
MEASURE = _tagged(
    "kind",
    hogql=_mapping({"kind": _text, "sql": _text}, {"trend_sql": _text}),
    insight=_mapping({"kind": _text, "short_id": _text, "url": _text, "name": _text}),
)
GOAL = _mapping(
    {"name": _text},
    {
        "id": _text,
        "primary": _flag,
        "period": _one_of("day", "week", "month"),
        "percent": _flag,
        "task": _text,
        "target": _nullable(TARGET),
        "measure": _nullable(MEASURE),
    },
)
LINK = _mapping({"title": _text, "target": _text}, {"note": _text})
OBJECT = _mapping({"kind": _one_of(*OBJECT_KINDS), "title": _text, "url": _http_url})
FRONTMATTER_LISTS: dict[str, Check] = {
    "goals": _nullable(_each(GOAL)),
    "reading": _nullable(_each(LINK)),
    "watching": _nullable(_each(OBJECT)),
}


def _lint_frontmatter_lists(lines: list[str]) -> list[str]:
    blocks: dict[str, list[Line]] = {}
    current: list[Line] | None = None
    for number, text in enumerate(lines, start=2):
        match = KEY_VALUE_RE.match(text)
        if match is not None:
            current = blocks.setdefault(match.group(1), []) if match.group(1) in FRONTMATTER_LISTS else None
        if current is not None:
            current.append((number, text))
    errors: list[str] = []
    for key, block in blocks.items():
        try:
            parsed = BlockParser(block).parse()
        except BlockSyntaxError as error:
            errors.append(f"{key}: {error}")
            continue
        errors.extend(FRONTMATTER_LISTS[key](parsed.get(key), key))
    return errors


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
dream=false
if [ "${1:-}" = "--dream" ]; then
    dream=true
    shift
fi
summary_file="${1:-}"
summary=""
if [ -n "$summary_file" ]; then
    summary="$(cat "$summary_file")"
fi
python3 scripts/lint
git rev-parse --verify origin/main >/dev/null
branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$dream" = true ]; then
    if [ -z "$summary" ]; then
        echo "publish: a scheduled dream needs a nonempty summary file" >&2
        exit 1
    fi
    target_branch="dream/$(date -u +%F)"
    if [ "$branch" != "$target_branch" ]; then
        branch="$target_branch"
        if git show-ref --verify --quiet "refs/heads/$branch"; then
            git checkout "$branch"
        else
            git checkout -b "$branch"
        fi
    fi
    git add --all
    if ! git diff --cached --quiet; then
        git -c user.name="PostHog Context Layer" -c user.email="context-layer@posthog.com" \\
            -c commit.gpgsign=false commit -m "dream: ${branch#dream/}" -m "$summary"
    fi
elif [ -n "$(git status --porcelain)" ]; then
    echo "publish: uncommitted edits; scheduled dreams must use --dream" >&2
    exit 1
fi
if [ "$(git rev-list --count "origin/main..$branch")" = 0 ]; then
    echo "publish: no changes"
    exit 0
fi
bundle="$(mktemp /tmp/context-layer-publish.XXXXXX.bundle)"
trap 'rm -f "$bundle"' EXIT
git bundle create "$bundle" "origin/main..$branch"
set --
if [ -n "$summary_file" ]; then
    set -- "$@" --form-string "summary=$summary"
fi
if [ "$branch" != "main" ]; then
    set -- "$@" -F "branch=$branch"
fi
curl -fsS -X POST \\
    -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
    -F "bundle=@$bundle" \\
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


def _frontmatter_lines(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            return lines[1:index]
    return []


def _frontmatter(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in _frontmatter_lines(path):
        key, separator, value = line.partition(":")
        if separator and key == key.strip() and key.strip():
            fields[key.strip()] = value.strip()
    return fields


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
