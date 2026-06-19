"""Business logic for the agent-memory tree.

The memory tree is a per-team set of markdown files. Object storage holds the
durable source of truth at `agent_memory/{team_id}/{path}`; `AgentMemoryFile`
rows are a Postgres-side index + cached copy that serve reads/listing and anchor
optimistic concurrency (compare-and-set on `version`).

All writes go through Postgres first inside a transaction (the CAS check and the
version bump must be atomic), then mirror the new body to object storage. The DB
row is authoritative for `version`; object storage is the durable byte store and
the "live shared filesystem" surface other tooling can point at.

This module owns ORM queries and storage I/O; the facade (`facade/api.py`) is a
thin async wrapper over it.
"""

from __future__ import annotations

import re

from django.db import IntegrityError, transaction

import structlog

from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.agent_memory.backend.models import AgentMemoryFile

logger = structlog.get_logger(__name__)

# Object-storage key prefix. {team_id} keeps every team's tree isolated under one
# root so a single `list_objects(prefix=...)` enumerates exactly one team.
_STORAGE_ROOT = "agent_memory"

# A memory file body is read verbatim into agent prompts, so cap it generously but
# firmly to keep a runaway write from bloating storage or a later prompt.
MAX_FILE_BYTES = 1_000_000

# Path safety: relative, forward-slash separated, markdown only. No absolute paths,
# no parent traversal, bounded segment/length so a path can't escape the team root
# or blow past the column width.
MAX_PATH_LENGTH = 1024
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class MemoryError(Exception):
    """Base class for memory-tree errors."""


class InvalidMemoryPathError(MemoryError, ValueError):
    """The supplied path is empty, absolute, traversing, or otherwise unsafe."""


class MemoryFileNotFoundError(MemoryError):
    """No file exists at the requested path for this team."""


class MemoryContentTooLargeError(MemoryError, ValueError):
    """The supplied content exceeds MAX_FILE_BYTES."""


class MemoryVersionConflictError(MemoryError):
    """Compare-and-set failed: the stored version differs from the one supplied.

    The caller must re-read the file, merge their change onto the current content,
    and retry the write with the freshly read version.
    """

    def __init__(self, path: str, expected_version: int, actual_version: int) -> None:
        self.path = path
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"version conflict on {path!r}: expected v{expected_version}, "
            f"stored is v{actual_version}; re-read and merge"
        )


def normalize_path(path: str) -> str:
    """Validate and canonicalize a memory path.

    Returns a clean relative path (no leading/trailing slashes, collapsed inner
    slashes). Raises InvalidMemoryPathError for anything that could escape the
    team root or isn't a markdown file.
    """
    if not path or not path.strip():
        raise InvalidMemoryPathError("path must be non-empty")
    candidate = path.strip().strip("/")
    if not candidate:
        raise InvalidMemoryPathError("path must contain at least one segment")
    if len(candidate) > MAX_PATH_LENGTH:
        raise InvalidMemoryPathError(f"path length {len(candidate)} exceeds max {MAX_PATH_LENGTH}")
    segments = [seg for seg in candidate.split("/") if seg != ""]
    if not segments:
        raise InvalidMemoryPathError("path must contain at least one segment")
    for seg in segments:
        if seg in (".", ".."):
            raise InvalidMemoryPathError("path may not contain '.' or '..' segments")
        if not _PATH_SEGMENT_RE.match(seg):
            raise InvalidMemoryPathError(
                f"path segment {seg!r} has invalid characters (allowed: letters, digits, '.', '_', '-')"
            )
    normalized = "/".join(segments)
    if not normalized.endswith(".md"):
        raise InvalidMemoryPathError("memory files must be markdown (end with '.md')")
    return normalized


def _storage_key(team_id: int, path: str) -> str:
    return f"{_STORAGE_ROOT}/{team_id}/{path}"


def _validate_content(content: str) -> None:
    size = len(content.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        raise MemoryContentTooLargeError(f"content is {size} bytes, exceeds max {MAX_FILE_BYTES}")


def _mirror_to_storage(team_id: int, path: str, content: str) -> None:
    """Write the body to object storage (durable SoT). Best-effort: a storage hiccup
    must not lose the DB row that already committed — the row is the cached copy and a
    later read repairs storage via re-write. Failures are logged, not raised."""
    try:
        object_storage.write(_storage_key(team_id, path), content)
    except Exception:
        logger.exception("agent_memory.storage_mirror_failed", team_id=team_id, path=path)


def _delete_from_storage(team_id: int, path: str) -> None:
    try:
        object_storage.delete(_storage_key(team_id, path))
    except Exception:
        logger.exception("agent_memory.storage_delete_failed", team_id=team_id, path=path)


def read_memory(*, team_id: int, path: str) -> AgentMemoryFile:
    """Return the file row at `path`, or raise MemoryFileNotFoundError."""
    normalized = normalize_path(path)
    with team_scope(team_id):
        row = AgentMemoryFile.objects.filter(path=normalized).first()
    if row is None:
        raise MemoryFileNotFoundError(f"no memory file at {normalized!r}")
    return row


def list_memory(*, team_id: int, prefix: str | None = None) -> list[AgentMemoryFile]:
    """List all files for the team, optionally filtered to a path prefix.

    `prefix` is a path fragment (e.g. "scouts/") — it is NOT required to be a full
    valid path, so a bare directory prefix works.
    """
    with team_scope(team_id):
        qs = AgentMemoryFile.objects.all()
        if prefix:
            # Keep a trailing slash so a directory prefix like "users/" matches only
            # files under that directory, not siblings like "users_archive/old.md".
            clean = prefix.strip().lstrip("/")
            if clean:
                qs = qs.filter(path__startswith=clean)
        return list(qs.order_by("path"))


def write_memory(
    *,
    team_id: int,
    path: str,
    content: str,
    expected_version: int | None,
    updated_by_id: int | None = None,
    updated_by_run: str | None = None,
) -> AgentMemoryFile:
    """Compare-and-set write.

    - `expected_version=None` means "create": succeeds only if the file does not
      yet exist (raises MemoryVersionConflictError if it does).
    - `expected_version=N` means "update an existing v N file": succeeds only if the
      stored version is exactly N (raises MemoryVersionConflictError otherwise, with
      the actual stored version so the caller can re-read and merge).

    On success the version is bumped and the body mirrored to object storage.
    """
    normalized = normalize_path(path)
    _validate_content(content)

    with team_scope(team_id), transaction.atomic():
        existing = AgentMemoryFile.objects.select_for_update().filter(path=normalized).first()
        if existing is None:
            if expected_version is not None and expected_version != 0:
                # Caller thought they were updating an existing file, but it's gone.
                raise MemoryVersionConflictError(normalized, expected_version, 0)
            try:
                row = AgentMemoryFile.objects.create(
                    team_id=team_id,
                    path=normalized,
                    content=content,
                    version=1,
                    updated_by_id=updated_by_id,
                    updated_by_run=updated_by_run,
                )
            except IntegrityError:
                # Lost the create race against a concurrent insert for the same
                # (team, path). Surface as a conflict so the caller re-reads.
                raise MemoryVersionConflictError(normalized, expected_version or 0, 1)
        else:
            if expected_version is None:
                # Caller asked to create, but the file already exists.
                raise MemoryVersionConflictError(normalized, 0, existing.version)
            if existing.version != expected_version:
                raise MemoryVersionConflictError(normalized, expected_version, existing.version)
            existing.content = content
            existing.version = existing.version + 1
            existing.updated_by_id = updated_by_id
            existing.updated_by_run = updated_by_run
            existing.save(update_fields=["content", "version", "updated_by", "updated_by_run", "updated_at"])
            row = existing

    _mirror_to_storage(team_id, normalized, row.content)
    return row


def append_section(
    *,
    team_id: int,
    path: str,
    heading: str,
    body: str,
    updated_by_id: int | None = None,
    updated_by_run: str | None = None,
) -> AgentMemoryFile:
    """Append or replace a single markdown section atomically.

    This is the preferred mutation for agents: it never clobbers the rest of the
    file, so two agents touching different sections of the same file don't lose each
    other's work. The whole read-modify-write runs under a row lock and an internal
    CAS retry, so it never raises a version conflict to the caller.

    `heading` is the section title (without leading '#'). If a section with that
    heading already exists (matched at any heading level), its body is replaced;
    otherwise a new `## {heading}` section is appended to the end of the file.
    """
    normalized = normalize_path(path)
    if not heading or not heading.strip():
        raise InvalidMemoryPathError("section heading must be non-empty")

    with team_scope(team_id), transaction.atomic():
        existing = AgentMemoryFile.objects.select_for_update().filter(path=normalized).first()
        current = existing.content if existing is not None else ""
        new_content = _upsert_section(current, heading.strip(), body.rstrip())
        _validate_content(new_content)

        if existing is None:
            try:
                # Nested atomic() = savepoint: on a lost create race the IntegrityError
                # rolls back only this savepoint, leaving the outer transaction usable
                # for the re-fetch below. Without it, Postgres aborts the whole
                # transaction and the re-fetch raises TransactionManagementError.
                with transaction.atomic():
                    row = AgentMemoryFile.objects.create(
                        team_id=team_id,
                        path=normalized,
                        content=new_content,
                        version=1,
                        updated_by_id=updated_by_id,
                        updated_by_run=updated_by_run,
                    )
            except IntegrityError:
                # A concurrent create won; re-fetch and merge onto its content.
                existing = AgentMemoryFile.objects.select_for_update().get(path=normalized)
                new_content = _upsert_section(existing.content, heading.strip(), body.rstrip())
                _validate_content(new_content)
                existing.content = new_content
                existing.version = existing.version + 1
                existing.updated_by_id = updated_by_id
                existing.updated_by_run = updated_by_run
                existing.save(update_fields=["content", "version", "updated_by", "updated_by_run", "updated_at"])
                row = existing
        else:
            existing.content = new_content
            existing.version = existing.version + 1
            existing.updated_by_id = updated_by_id
            existing.updated_by_run = updated_by_run
            existing.save(update_fields=["content", "version", "updated_by", "updated_by_run", "updated_at"])
            row = existing

    _mirror_to_storage(team_id, normalized, row.content)
    return row


def delete_memory(*, team_id: int, path: str) -> bool:
    """Delete a file. Returns whether anything was removed (False = no-op)."""
    normalized = normalize_path(path)
    with team_scope(team_id), transaction.atomic():
        existing = AgentMemoryFile.objects.select_for_update().filter(path=normalized).first()
        if existing is None:
            return False
        existing.delete()
    _delete_from_storage(team_id, normalized)
    return True


def _upsert_section(content: str, heading: str, body: str) -> str:
    """Return `content` with the `heading` section's body set to `body`.

    A section runs from its heading line (`#`..`######` followed by the heading
    text) to just before the next heading of the same-or-shallower level (or EOF).
    Matching is case-insensitive on the trimmed heading text and level-agnostic, so
    a `## Foo` written earlier is still found if the agent later asks for `Foo`.
    If no matching section exists, a new `## {heading}` is appended.
    """
    section_block = f"## {heading}\n\n{body}".rstrip() + "\n"
    lines = content.splitlines()

    match_idx = None
    match_level = 0
    heading_re = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m and m.group(2).strip().lower() == heading.lower():
            match_idx = i
            match_level = len(m.group(1))
            break

    if match_idx is None:
        prefix = content.rstrip()
        if prefix:
            return f"{prefix}\n\n{section_block}"
        return section_block

    # Find the end of the matched section: the next heading at the same or shallower level.
    end_idx = len(lines)
    for j in range(match_idx + 1, len(lines)):
        m = heading_re.match(lines[j])
        if m and len(m.group(1)) <= match_level:
            end_idx = j
            break

    before = lines[:match_idx]
    after = lines[end_idx:]
    # Preserve the original heading line (keeps the author's heading level).
    rebuilt_section = f"{lines[match_idx]}\n\n{body}".rstrip()
    parts = []
    if before:
        parts.append("\n".join(before).rstrip())
    parts.append(rebuilt_section)
    if after:
        parts.append("\n".join(after).strip())
    return "\n\n".join(p for p in parts if p).rstrip() + "\n"
