"""S3 reader for the AutoML task layout.

Layout assumed under `<bucket>/tasks/<task_name>/`:

    spec.yaml
    queries/v1.sql, v2.sql, HEAD
    runs/<run_id>/manifest.yaml
    runs/<run_id>/predictions.parquet
    runs/<run_id>/features.parquet
    runs/<run_id>/splits/{train,val,test}.parquet
    runs/<run_id>/model.tar
    HEAD                              # contents = "runs/<run_id>/" of the current shipped run

S3 has no symlinks, so each `HEAD` is a plain text object whose body is the
relative target (e.g. `v2.sql` or `runs/2026-05-13_21-42-13/`).
"""

import io
import os
from dataclasses import dataclass
from typing import Optional

import yaml
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

from posthog.storage.object_storage import ObjectStorageClient, object_storage_client

TASKS_PREFIX = "tasks/"


def _bucket() -> str:
    return os.getenv("AUTOML_OBJECT_STORAGE_BUCKET", "automl")


def _client() -> ObjectStorageClient:
    return object_storage_client()


def _read_text(key: str) -> Optional[str]:
    raw = _client().read(_bucket(), key, missing_ok=True)
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _read_bytes(key: str) -> Optional[bytes]:
    return _client().read_bytes(_bucket(), key, missing_ok=True)


def _list(prefix: str) -> list[str]:
    return _client().list_objects(_bucket(), prefix) or []


@dataclass(frozen=True)
class TaskSummary:
    name: str
    has_spec: bool
    spec: Optional[dict]
    current_query_version: Optional[str]
    current_run_id: Optional[str]
    current_run_manifest: Optional[dict]
    run_count: int


@dataclass(frozen=True)
class TaskDetail:
    name: str
    spec: Optional[dict]
    spec_raw: Optional[str]
    queries: list[str]
    current_query_version: Optional[str]
    runs: list["RunSummary"]
    current_run_id: Optional[str]


@dataclass(frozen=True)
class RunSummary:
    id: str
    shipped: bool
    is_current: bool
    manifest: Optional[dict]


@dataclass(frozen=True)
class RunDetail:
    task_name: str
    id: str
    manifest: Optional[dict]
    manifest_raw: Optional[str]
    artifacts: list[str]
    is_current: bool


def list_tasks() -> list[TaskSummary]:
    """Discover task names by listing keys under tasks/ and pulling unique prefixes."""
    keys = _list(TASKS_PREFIX)
    names: set[str] = set()
    run_counts: dict[str, set[str]] = {}
    for key in keys:
        rest = key[len(TASKS_PREFIX) :]
        if not rest:
            continue
        head, _, tail = rest.partition("/")
        if not head:
            continue
        names.add(head)
        if tail.startswith("runs/"):
            run_id, slash, _ = tail[len("runs/") :].partition("/")
            # Only count it as a run if it's a real directory (has a slash + deeper path).
            # `runs/HEAD`, `runs/MODEL_HEAD` etc. are pointer files, not runs.
            if run_id and slash:
                run_counts.setdefault(head, set()).add(run_id)

    summaries: list[TaskSummary] = []
    for name in sorted(names):
        spec_raw = _read_text(f"{TASKS_PREFIX}{name}/spec.yaml")
        spec = _safe_yaml_load(spec_raw)
        run_pointer = _read_text(f"{TASKS_PREFIX}{name}/HEAD")
        query_pointer = _read_text(f"{TASKS_PREFIX}{name}/queries/HEAD")
        current_run_id = _extract_run_id(run_pointer)
        current_run_manifest = None
        if current_run_id:
            current_run_manifest = _safe_yaml_load(
                _read_text(f"{TASKS_PREFIX}{name}/runs/{current_run_id}/manifest.yaml")
            )
        summaries.append(
            TaskSummary(
                name=name,
                has_spec=spec is not None,
                spec=spec,
                current_query_version=_extract_query_version(query_pointer),
                current_run_id=current_run_id,
                current_run_manifest=current_run_manifest,
                run_count=len(run_counts.get(name, set())),
            )
        )
    return summaries


def get_task(name: str) -> Optional[TaskDetail]:
    """Read everything we can about a single task — spec, queries, runs, HEADs."""
    base = f"{TASKS_PREFIX}{name}/"
    keys = _list(base)
    if not keys:
        return None

    spec_raw = _read_text(f"{base}spec.yaml")
    spec = _safe_yaml_load(spec_raw)

    queries: set[str] = set()
    run_ids: set[str] = set()
    for key in keys:
        suffix = key[len(base) :]
        if suffix.startswith("queries/") and suffix.endswith(".sql"):
            queries.add(suffix[len("queries/") :])
        elif suffix.startswith("runs/"):
            run_id, slash, _ = suffix[len("runs/") :].partition("/")
            if run_id and slash:
                run_ids.add(run_id)

    current_run_id = _extract_run_id(_read_text(f"{base}HEAD"))
    current_query_version = _extract_query_version(_read_text(f"{base}queries/HEAD"))

    run_summaries: list[RunSummary] = []
    for run_id in sorted(run_ids, reverse=True):
        manifest_raw = _read_text(f"{base}runs/{run_id}/manifest.yaml")
        manifest = _safe_yaml_load(manifest_raw)
        run_summaries.append(
            RunSummary(
                id=run_id,
                shipped=bool(manifest and manifest.get("shipped", False)),
                is_current=run_id == current_run_id,
                manifest=manifest,
            )
        )

    return TaskDetail(
        name=name,
        spec=spec,
        spec_raw=spec_raw,
        queries=sorted(queries),
        current_query_version=current_query_version,
        runs=run_summaries,
        current_run_id=current_run_id,
    )


def get_query(task_name: str, version: str) -> Optional[str]:
    if not _safe_segment(version) or not version.endswith(".sql"):
        return None
    return _read_text(f"{TASKS_PREFIX}{task_name}/queries/{version}")


def get_run(task_name: str, run_id: str) -> Optional[RunDetail]:
    if not _safe_segment(run_id):
        return None
    base = f"{TASKS_PREFIX}{task_name}/runs/{run_id}/"
    keys = _list(base)
    if not keys:
        return None

    manifest_raw = _read_text(f"{base}manifest.yaml")
    manifest = _safe_yaml_load(manifest_raw)
    current_run_id = _extract_run_id(_read_text(f"{TASKS_PREFIX}{task_name}/HEAD"))
    artifacts = sorted(key[len(base) :] for key in keys if key != f"{base}manifest.yaml")

    return RunDetail(
        task_name=task_name,
        id=run_id,
        manifest=manifest,
        manifest_raw=manifest_raw,
        artifacts=artifacts,
        is_current=run_id == current_run_id,
    )


def preview_parquet(
    task_name: str,
    run_id: str,
    relative_path: str,
    limit: int = 50,
    offset: int = 0,
) -> Optional[dict]:
    """Return columns + a window of rows from a parquet artifact, as JSON-safe values."""
    if not _safe_segment(run_id) or ".." in relative_path or relative_path.startswith("/"):
        return None
    if not relative_path.endswith(".parquet"):
        return None

    key = f"{TASKS_PREFIX}{task_name}/runs/{run_id}/{relative_path}"
    try:
        data = _read_bytes(key)
    except ClientError:
        return None
    if data is None:
        return None

    table = pq.read_table(io.BytesIO(data))
    safe_offset = max(0, min(offset, table.num_rows))
    sliced = table.slice(safe_offset, limit)
    columns = [field.name for field in sliced.schema]
    rows: list[dict] = []
    for record in sliced.to_pylist():
        rows.append({col: _json_safe(record.get(col)) for col in columns})
    return {
        "columns": columns,
        "rows": rows,
        "total_rows": table.num_rows,
        "returned_rows": len(rows),
        "offset": safe_offset,
    }


def _safe_segment(value: str) -> bool:
    """Reject anything that could climb out of the task prefix."""
    return bool(value) and "/" not in value and ".." not in value


def _safe_yaml_load(raw: Optional[str]) -> Optional[dict]:
    if raw is None:
        return None
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _extract_run_id(pointer: Optional[str]) -> Optional[str]:
    if not pointer:
        return None
    pointer = pointer.strip().rstrip("/")
    if not pointer:
        return None
    if pointer.startswith("runs/"):
        pointer = pointer[len("runs/") :]
    if "/" in pointer:
        return None
    return pointer


def _extract_query_version(pointer: Optional[str]) -> Optional[str]:
    if not pointer:
        return None
    pointer = pointer.strip().rstrip("/")
    if not pointer:
        return None
    if pointer.startswith("queries/"):
        pointer = pointer[len("queries/") :]
    if "/" in pointer:
        return None
    return pointer


def _json_safe(value: object) -> object:
    """Pyarrow returns datetimes/decimals/bytes that aren't JSON-serializable."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def bucket_name() -> str:
    return _bucket()
