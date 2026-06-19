"""Public facade for the agent-memory tree.

This is the only module other products (signals, the Slack agents, …) may import.
It exposes async functions that wrap the synchronous store logic so agent code
running in async contexts (Temporal activities, the scout harness) can call in
without juggling thread bridges.

Callers pass `team_id` plus an optional human (`updated_by_id`) and run
identifier (`updated_by_run`) for attribution. Everything is team-scoped: a write
or read for one team can never touch another's tree.
"""

from __future__ import annotations

from posthog.sync import database_sync_to_async

from products.agent_memory.backend import logic
from products.agent_memory.backend.facade import contracts
from products.agent_memory.backend.models import AgentMemoryFile

# Re-export the domain errors so callers handle conflicts/not-found without importing
# the internal logic module (which would break product isolation).
InvalidMemoryPathError = logic.InvalidMemoryPathError
MemoryFileNotFoundError = logic.MemoryFileNotFoundError
MemoryVersionConflictError = logic.MemoryVersionConflictError
MemoryContentTooLargeError = logic.MemoryContentTooLargeError

# Re-export the size/length limits so the presentation layer can bound its input
# fields without reaching into the internal logic module.
MAX_FILE_BYTES = logic.MAX_FILE_BYTES
MAX_PATH_LENGTH = logic.MAX_PATH_LENGTH


def _to_file(row: AgentMemoryFile) -> contracts.MemoryFile:
    return contracts.MemoryFile(
        path=row.path,
        content=row.content,
        version=row.version,
        updated_by_id=row.updated_by_id,
        updated_by_run=row.updated_by_run,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_summary(row: AgentMemoryFile) -> contracts.MemoryFileSummary:
    return contracts.MemoryFileSummary(
        path=row.path,
        version=row.version,
        size_bytes=len(row.content.encode("utf-8")),
        updated_by_run=row.updated_by_run,
        updated_at=row.updated_at,
    )


async def aread_memory(*, team_id: int, path: str) -> contracts.MemoryFile:
    """Read a single memory file. Raises MemoryFileNotFoundError if absent."""
    row = await database_sync_to_async(logic.read_memory, thread_sensitive=True)(team_id=team_id, path=path)
    return _to_file(row)


async def alist_memory(*, team_id: int, prefix: str | None = None) -> list[contracts.MemoryFileSummary]:
    """List the team's memory files (metadata only), optionally under a path prefix."""
    rows = await database_sync_to_async(logic.list_memory, thread_sensitive=True)(team_id=team_id, prefix=prefix)
    return [_to_summary(row) for row in rows]


async def awrite_memory(
    *,
    team_id: int,
    path: str,
    content: str,
    expected_version: int | None,
    updated_by_id: int | None = None,
    updated_by_run: str | None = None,
) -> contracts.MemoryFile:
    """Compare-and-set write. Raises MemoryVersionConflictError on a version mismatch.

    Pass `expected_version=None` to create a new file, or the version you last read to
    update an existing one. Prefer `aappend_section` for agent mutations — it never
    clobbers concurrent edits.
    """
    row = await database_sync_to_async(logic.write_memory, thread_sensitive=True)(
        team_id=team_id,
        path=path,
        content=content,
        expected_version=expected_version,
        updated_by_id=updated_by_id,
        updated_by_run=updated_by_run,
    )
    return _to_file(row)


async def aappend_section(
    *,
    team_id: int,
    path: str,
    heading: str,
    body: str,
    updated_by_id: int | None = None,
    updated_by_run: str | None = None,
) -> contracts.MemoryFile:
    """Append or replace one markdown section atomically — the safe agent mutation.

    Never raises a version conflict: the read-modify-write is serialized under a row
    lock, so concurrent agents editing different sections of the same file don't
    clobber each other.
    """
    row = await database_sync_to_async(logic.append_section, thread_sensitive=True)(
        team_id=team_id,
        path=path,
        heading=heading,
        body=body,
        updated_by_id=updated_by_id,
        updated_by_run=updated_by_run,
    )
    return _to_file(row)


async def adelete_memory(*, team_id: int, path: str) -> bool:
    """Delete a memory file. Returns False if there was nothing to delete."""
    return await database_sync_to_async(logic.delete_memory, thread_sensitive=True)(team_id=team_id, path=path)
