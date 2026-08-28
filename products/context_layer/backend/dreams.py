"""Read dream runs out of the wiki's git history.

A dreaming run lands as one two-parent merge commit whose subject is
`dream: <YYYY-MM-DD>` and whose body is the run summary, so the history itself
is the record: `git log --merges` lists the runs and `git diff <merge>^1
<merge>` shows what the night changed. Lists are cached per head sha (a new
dream moves the head), and one run's diff is immutable, so its cache entry is
keyed by the merge sha alone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from posthog.dataclasses import frozen
from posthog.utils import get_safe_cache, safe_cache_set

from products.context_layer.backend import store

CACHE_TTL_SECONDS = 24 * 60 * 60
DREAM_SUBJECT_PREFIX = "dream: "
# A dream touches content pages only; these caps keep one oversized night from
# ballooning the API response. Files past the cap are still listed, with their
# patch replaced by a truncation note.
DREAM_MAX_FILES = 500
DREAM_MAX_PATCH_BYTES_PER_FILE = 100_000

# git log record and field separators.
_RECORD_SEPARATOR = "\x1e"
_FIELD_SEPARATOR = "\x1f"


class DreamNotFoundError(store.ContextLayerStoreError):
    pass


@frozen
class DreamRun:
    sha: str
    date: str
    committed_at: datetime
    summary: str
    pages_added: int
    pages_modified: int
    pages_deleted: int


@frozen
class DreamFileDiff:
    path: str
    status: str  # added | modified | deleted
    patch: str
    truncated: bool


@frozen
class DreamRunDetail:
    run: DreamRun
    files: list[DreamFileDiff]


@frozen
class DreamRunList:
    head_sha: str
    dreams: list[DreamRun]


_STATUS_MAP = {"A": "added", "M": "modified", "D": "deleted"}


def _list_cache_key(organization_id: uuid.UUID | str, head_sha: str) -> str:
    return f"context_layer:dreams:{organization_id}:{head_sha}"


def _detail_cache_key(organization_id: uuid.UUID | str, sha: str) -> str:
    return f"context_layer:dream:{organization_id}:{sha}"


def list_dream_runs(organization_id: uuid.UUID | str) -> DreamRunList:
    """Every dream run on the wiki's main branch, newest first."""
    head_sha = store.get_config(organization_id).head_sha
    cached = get_safe_cache(_list_cache_key(organization_id, head_sha))
    if cached is not None:
        return DreamRunList(
            head_sha=head_sha, dreams=[_dream_run_from_dict(entry) for entry in cached if isinstance(entry, dict)]
        )
    with store.checkout_repo(organization_id) as checkout:
        dreams = _read_dream_runs(checkout)
    safe_cache_set(
        _list_cache_key(organization_id, head_sha),
        [_dream_run_to_dict(dream) for dream in dreams],
        CACHE_TTL_SECONDS,
    )
    return DreamRunList(head_sha=head_sha, dreams=dreams)


def get_dream_run(organization_id: uuid.UUID | str, sha: str) -> DreamRunDetail:
    """One dream run with the per-file patches it landed.

    The sha must name a dream merge on main, so a caller cannot diff arbitrary
    commits through this endpoint."""
    cached = get_safe_cache(_detail_cache_key(organization_id, sha))
    if cached is not None:
        return _dream_detail_from_dict(cached)
    with store.checkout_repo(organization_id) as checkout:
        dreams = {dream.sha: dream for dream in _read_dream_runs(checkout)}
        run = dreams.get(sha)
        if run is None:
            raise DreamNotFoundError(f"no dream run at {sha}")
        files = _read_dream_files(checkout, sha)
    detail = DreamRunDetail(run=run, files=files)
    safe_cache_set(_detail_cache_key(organization_id, sha), _dream_detail_to_dict(detail), CACHE_TTL_SECONDS)
    return detail


def _read_dream_runs(checkout: store.RepoCheckout) -> list[DreamRun]:
    log = store._run_git(
        [
            "log",
            "--merges",
            f"--format=%H{_FIELD_SEPARATOR}%cI{_FIELD_SEPARATOR}%s{_FIELD_SEPARATOR}%b{_RECORD_SEPARATOR}",
            "main",
        ],
        checkout.path,
    )
    dreams: list[DreamRun] = []
    for record in log.split(_RECORD_SEPARATOR):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, rest = record.partition(_FIELD_SEPARATOR)
        committed_at, _, rest = rest.partition(_FIELD_SEPARATOR)
        subject, _, body = rest.partition(_FIELD_SEPARATOR)
        if not subject.startswith(DREAM_SUBJECT_PREFIX):
            continue
        counts = _dream_change_counts(checkout, sha)
        dreams.append(
            DreamRun(
                sha=sha,
                date=subject.removeprefix(DREAM_SUBJECT_PREFIX).strip(),
                committed_at=datetime.fromisoformat(committed_at),
                summary=body.strip(),
                pages_added=counts["A"],
                pages_modified=counts["M"],
                pages_deleted=counts["D"],
            )
        )
    return dreams


def _dream_change_counts(checkout: store.RepoCheckout, sha: str) -> dict[str, int]:
    counts = {"A": 0, "M": 0, "D": 0}
    for line in store._run_git(["diff", "--name-status", f"{sha}^1", sha, "--", "*.md"], checkout.path).splitlines():
        status = line.split("\t", 1)[0][:1]
        if status in counts:
            counts[status] += 1
    return counts


def _read_dream_files(checkout: store.RepoCheckout, sha: str) -> list[DreamFileDiff]:
    name_status = store._run_git(
        ["diff", "--name-status", "--no-renames", f"{sha}^1", sha, "--", "*.md"], checkout.path
    )
    files: list[DreamFileDiff] = []
    for line in name_status.splitlines()[:DREAM_MAX_FILES]:
        status_code, _, path = line.partition("\t")
        status = _STATUS_MAP.get(status_code[:1], "modified")
        patch = store._run_git(["diff", f"{sha}^1", sha, "--", path], checkout.path)
        truncated = False
        if len(patch.encode("utf-8")) > DREAM_MAX_PATCH_BYTES_PER_FILE:
            patch = patch.encode("utf-8")[:DREAM_MAX_PATCH_BYTES_PER_FILE].decode("utf-8", errors="ignore")
            truncated = True
        files.append(DreamFileDiff(path=path, status=status, patch=patch, truncated=truncated))
    return files


def _dream_run_to_dict(dream: DreamRun) -> dict[str, object]:
    return {
        "sha": dream.sha,
        "date": dream.date,
        "committed_at": dream.committed_at.astimezone(UTC).isoformat(),
        "summary": dream.summary,
        "pages_added": dream.pages_added,
        "pages_modified": dream.pages_modified,
        "pages_deleted": dream.pages_deleted,
    }


def _dream_run_from_dict(data: dict[str, object]) -> DreamRun:
    return DreamRun(
        sha=str(data["sha"]),
        date=str(data["date"]),
        committed_at=datetime.fromisoformat(str(data["committed_at"])),
        summary=str(data["summary"]),
        pages_added=int(str(data["pages_added"])),
        pages_modified=int(str(data["pages_modified"])),
        pages_deleted=int(str(data["pages_deleted"])),
    )


def _dream_detail_to_dict(detail: DreamRunDetail) -> dict[str, object]:
    return {
        "run": _dream_run_to_dict(detail.run),
        "files": [
            {"path": file.path, "status": file.status, "patch": file.patch, "truncated": file.truncated}
            for file in detail.files
        ],
    }


def _dream_detail_from_dict(data: dict[str, object]) -> DreamRunDetail:
    run_data = data["run"]
    files_data = data["files"]
    if not isinstance(run_data, dict) or not isinstance(files_data, list):
        raise ValueError("malformed cached dream detail")
    return DreamRunDetail(
        run=_dream_run_from_dict(run_data),
        files=[
            DreamFileDiff(
                path=str(file["path"]),
                status=str(file["status"]),
                patch=str(file["patch"]),
                truncated=bool(file["truncated"]),
            )
            for file in files_data
            if isinstance(file, dict)
        ],
    )
