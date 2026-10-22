import io
import json
import asyncio
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import asdict, field, fields
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from django.db.models import QuerySet

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from structlog.typing import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    AccountPropertySyncRunOutcome,
    complete_account_property_sync_segment_runs,
    finalize_account_property_sync_runs,
    finish_account_property_sync_runs,
)
from products.customer_analytics.backend.logic.custom_property_values import (
    InvalidCustomPropertyValue,
    set_synced_custom_property_value,
)
from products.customer_analytics.backend.metrics import record_account_property_sync_phase_duration
from products.customer_analytics.backend.models import Account, CustomPropertySource, TargetType
from products.customer_analytics.backend.models.custom_property_sync_run import (
    SyncPhase,
    SyncSegment as AccountPropertySyncSegment,
    SyncStatus,
)
from products.data_warehouse.backend.facade.api import aget_s3_client, get_s3_client
from products.warehouse_sources.backend.facade.hooks import WarehouseBinding
from products.warehouse_sources.backend.facade.temporal import (
    account_property_completion_prefix,
    account_property_job_staged_prefix,
    account_property_snapshot_prefix,
)

if TYPE_CHECKING:
    from s3fs import S3FileSystem

logger = structlog.get_logger(__name__)

_ACCOUNT_LOOKUP_CHUNK_SIZE = 1_000
_PARQUET_BATCH_SIZE = 50_000
_CHECKPOINT_INTERVAL_SECONDS = 60.0
_SEGMENTS_REQUIRED_FOR_CLEANUP = frozenset({"tracked", "ignored"})
_COUNT_KEYS = ("rows_read", "changed", "matched", "written", "source_errors", "source_count")
_RUN_FAILED_ERROR = "Couldn't update accounts. Run the source view again. If it keeps failing, contact support."
_INVALID_VALUE_ERROR = (
    "A warehouse value doesn't match this property's type. Update the source data, then run the view again."
)


class AccountPropertySyncPhase(StrEnum):
    LOAD_STATE = "load_state"
    READ_STAGED_ROWS = "read_staged_rows"
    DIFF_VALUES = "diff_values"
    MATCH_ACCOUNTS = "match_accounts"
    APPLY_VALUES = "apply_values"
    PERSIST_STATE = "persist_state"


class AccountPropertySourceValueError(Exception):
    def __init__(self, message: str, *, counts: dict[str, int]) -> None:
        super().__init__(message)
        self.counts = counts.copy()


class AccountPropertySourceRejectedError(Exception):
    pass


def _empty_counts() -> dict[str, int]:
    return dict.fromkeys(_COUNT_KEYS, 0)


@frozen
class AppliedSourceValues:
    written: int
    hashes: dict[str, str]
    failed: bool


class _SnapshotS3Client(Protocol):
    async def _ls(self, path: str, *, detail: bool) -> dict[str, dict[str, Any]] | list[dict[str, Any]]: ...

    async def _cat_file(self, path: str) -> bytes: ...

    async def _pipe_file(self, path: str, data: bytes) -> None: ...

    async def _rm(self, paths: str | list[str], *, recursive: bool = False) -> None: ...


@frozen
class _SnapshotMerge:
    hashes: dict[str, str]
    complete: bool


@frozen(frozen=False)
class SourceSyncState:
    source: CustomPropertySource
    prior_hashes: dict[str, str]
    applied_hashes: dict[str, str] = field(default_factory=dict)
    rows_read: int = 0
    changed: int = 0
    matched: int = 0
    written: int = 0
    error: str | None = None


@frozen
class SourceSyncCheckpoint:
    next_batch: int
    rows_read: int
    changed: int
    matched: int
    written: int
    failed: bool
    key_column: str
    source_column: str

    def __post_init__(self) -> None:
        for name in ("next_batch", "rows_read", "changed", "matched", "written"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.failed, bool):
            raise ValueError("failed must be a boolean")
        if not isinstance(self.key_column, str) or not isinstance(self.source_column, str):
            raise ValueError("key_column and source_column must be strings")

    @classmethod
    def from_state(cls, state: SourceSyncState, next_batch: int) -> "SourceSyncCheckpoint":
        return cls(
            next_batch=next_batch,
            rows_read=state.rows_read,
            changed=state.changed,
            matched=state.matched,
            written=state.written,
            failed=state.error is not None,
            key_column=state.source.key_column,
            source_column=state.source.source_column or "",
        )

    def matches_mapping(self, source: CustomPropertySource) -> bool:
        return (self.key_column, self.source_column) == (source.key_column, source.source_column)

    @classmethod
    def from_heartbeat_details(cls, details: Sequence[object]) -> "SourceSyncCheckpoint | None":
        if not details or not isinstance(details[0], dict):
            return None
        stored = details[0]
        try:
            return cls(**{checkpoint_field.name: stored[checkpoint_field.name] for checkpoint_field in fields(cls)})
        except (KeyError, ValueError):
            return None

    def to_heartbeat_details(self) -> dict[str, int | bool | str]:
        return asdict(self)

    def restore(self, state: SourceSyncState, counts: dict[str, int]) -> None:
        for key in ("rows_read", "changed", "matched", "written"):
            setattr(state, key, getattr(self, key))
            counts[key] = getattr(self, key)
        if self.failed:
            state.error = _INVALID_VALUE_ERROR


def _record_phase_duration(
    log: FilteringBoundLogger,
    segment: AccountPropertySyncSegment,
    phase: AccountPropertySyncPhase,
    started_at: float,
    details: dict[str, bool | float | int | str],
) -> None:
    duration_seconds = asyncio.get_running_loop().time() - started_at
    log.info(
        "Account-property sync phase completed",
        phase=phase.value,
        duration_seconds=duration_seconds,
        **details,
    )
    record_account_property_sync_phase_duration(
        phase=phase.value,
        segment=segment.value,
        duration_seconds=duration_seconds,
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json_safe(value), sort_keys=True).encode("utf-8")).hexdigest()


def _source_values(rows: list[dict[str, Any]], key_column: str, source_column: str) -> dict[str, Any]:
    return {
        str(row[key_column]): _json_safe(row[source_column])
        for row in rows
        if row.get(key_column) is not None and source_column in row
    }


def _decode_parquet_rows(data: bytes) -> list[dict[str, Any]]:
    return pq.read_table(io.BytesIO(data)).to_pylist()


def _encode_snapshot(hashes: dict[str, str]) -> bytes:
    table = pa.table({"external_id": list(hashes), "value_hash": list(hashes.values())})
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer, compression="zstd")
    return buffer.getvalue().to_pybytes()


def _parquet_batches(data: bytes) -> Iterator[pa.RecordBatch]:
    return pq.ParquetFile(io.BytesIO(data)).iter_batches(batch_size=_PARQUET_BATCH_SIZE)


def _projected_parquet_batches(s3_client: "S3FileSystem", path: str, columns: list[str]) -> Iterator[pa.RecordBatch]:
    # Read-ahead can fetch unselected column chunks, which defeats per-source projection.
    with s3_client.open(path, "rb", cache_type="none") as file:
        yield from pq.ParquetFile(file, pre_buffer=False).iter_batches(batch_size=_PARQUET_BATCH_SIZE, columns=columns)


async def _iter_parquet_row_batches(
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    *,
    columns: list[str] | None = None,
    skip_batches: int = 0,
) -> AsyncIterator[list[dict[str, Any]]]:
    skipped = 0
    prefix = account_property_job_staged_prefix(team_id, binding, job_id)
    async with aget_s3_client() as s3_client:
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            return
        entries = listing.values() if isinstance(listing, dict) else listing
        file_paths = sorted(entry["Key"] for entry in entries if entry.get("type") != "directory")
        for file_path in file_paths:
            if columns is None:
                data = await s3_client._cat_file(_s3_uri(file_path))
                batches = await asyncio.to_thread(_parquet_batches, data)
            else:
                batches = _projected_parquet_batches(get_s3_client(), _s3_uri(file_path), columns)
            while (batch := await asyncio.to_thread(next, batches, None)) is not None:
                if skipped < skip_batches:
                    skipped += 1
                    continue
                yield await asyncio.to_thread(batch.to_pylist)


def _s3_uri(key: str) -> str:
    return key if key.startswith("s3://") else f"s3://{key}"


def _s3_key(key: str) -> str:
    return key.removeprefix("s3://").lstrip("/")


async def _list_snapshot_files(s3_client: _SnapshotS3Client, prefix: str) -> list[str]:
    try:
        listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
    except FileNotFoundError:
        return []
    entries = listing.values() if isinstance(listing, dict) else listing
    entries_by_key = sorted(
        (entry for entry in entries if entry.get("type") != "directory"), key=lambda entry: entry["Key"]
    )
    entries_without_timestamp = [entry for entry in entries_by_key if entry.get("LastModified") is None]
    entries_with_timestamp = sorted(
        (entry for entry in entries_by_key if entry.get("LastModified") is not None),
        key=lambda entry: entry["LastModified"],
    )
    return [entry["Key"] for entry in [*entries_without_timestamp, *entries_with_timestamp]]


async def _merge_snapshot_files(s3_client: _SnapshotS3Client, file_keys: list[str]) -> _SnapshotMerge:
    hashes: dict[str, str] = {}
    complete = True
    for key in file_keys:
        try:
            data = await s3_client._cat_file(_s3_uri(key))
        except FileNotFoundError:
            complete = False
            continue
        for row in await asyncio.to_thread(_decode_parquet_rows, data):
            hashes[str(row["external_id"])] = str(row["value_hash"])
    return _SnapshotMerge(hashes=hashes, complete=complete)


async def _read_snapshot_hashes(
    team_id: int, binding: WarehouseBinding, source_id: str, segment: AccountPropertySyncSegment
) -> dict[str, str]:
    prefix = account_property_snapshot_prefix(team_id, binding, source_id, segment.value)
    async with aget_s3_client() as s3_client:
        merge = await _merge_snapshot_files(s3_client, await _list_snapshot_files(s3_client, prefix))
        return merge.hashes if merge.complete else {}


async def _write_snapshot_delta(
    team_id: int,
    binding: WarehouseBinding,
    source_id: str,
    segment: AccountPropertySyncSegment,
    name: str,
    hashes: dict[str, str],
) -> None:
    if not hashes:
        return
    prefix = account_property_snapshot_prefix(team_id, binding, source_id, segment.value)
    snapshot = await asyncio.to_thread(_encode_snapshot, hashes)
    async with aget_s3_client() as s3_client:
        await s3_client._pipe_file(_s3_uri(f"{prefix}/{name}.parquet"), snapshot)


async def _write_snapshot_hashes(
    team_id: int,
    binding: WarehouseBinding,
    source_id: str,
    segment: AccountPropertySyncSegment,
    job_id: str,
    hashes: dict[str, str],
) -> None:
    prefix = account_property_snapshot_prefix(team_id, binding, source_id, segment.value)
    path = f"{prefix}/{job_id}.parquet"
    async with aget_s3_client() as s3_client:
        existing_files = await _list_snapshot_files(s3_client, prefix)
        if not hashes and len(existing_files) <= 1:
            return
        merge = await _merge_snapshot_files(s3_client, existing_files)
        if not hashes and not merge.complete:
            return
        merged = {**merge.hashes, **hashes} if merge.complete else hashes
        snapshot = await asyncio.to_thread(_encode_snapshot, merged)
        await s3_client._pipe_file(_s3_uri(path), snapshot)
        if not merge.complete:
            return
        stale = [file_path for file_path in existing_files if _s3_key(file_path) != _s3_key(path)]
        if stale:
            stale_uris = [_s3_uri(file_path) for file_path in stale]
            try:
                await s3_client._rm(stale_uris)
            except FileNotFoundError:
                for stale_uri in stale_uris:
                    try:
                        await s3_client._rm(stale_uri)
                    except FileNotFoundError:
                        continue


def _matching_account_ids(
    team_id: int, segment: AccountPropertySyncSegment, external_ids: list[str]
) -> dict[str, UUID]:
    matching: dict[str, UUID] = {}
    for start in range(0, len(external_ids), _ACCOUNT_LOOKUP_CHUNK_SIZE):
        chunk = external_ids[start : start + _ACCOUNT_LOOKUP_CHUNK_SIZE]
        accounts = Account.objects.for_team(team_id).filter(
            external_id__in=chunk,
            churned_at__isnull=True,
        )
        if segment == AccountPropertySyncSegment.TRACKED:
            accounts = accounts.filter(ignored_at__isnull=True)
        else:
            accounts = accounts.filter(ignored_at__isnull=False)
        matching.update(
            (external_id, account_id)
            for external_id, account_id in accounts.values_list("external_id", "id")
            if external_id
        )
    return matching


def _apply_source_values(
    team_id: int,
    source: CustomPropertySource,
    account_ids: dict[str, UUID],
    changed: dict[str, Any],
    segment: AccountPropertySyncSegment,
) -> AppliedSourceValues:
    written = 0
    applied_hashes: dict[str, str] = {}
    source_failed = False
    for external_id, account_id in account_ids.items():
        value = changed[external_id]
        try:
            did_write = set_synced_custom_property_value(
                team_id=team_id,
                account_id=account_id,
                definition=source.definition,
                value=value,
            )
        except InvalidCustomPropertyValue as error:
            source_failed = True
            logger.warning(
                "account-property sync rejected a source value",
                team_id=team_id,
                source_id=str(source.id),
                segment=segment.value,
                error=str(error),
            )
            continue
        if did_write:
            written += 1
        applied_hashes[external_id] = _value_hash(value)
    return AppliedSourceValues(written=written, hashes=applied_hashes, failed=source_failed)


def _enabled_sources_queryset(team_id: int, binding: WarehouseBinding) -> QuerySet[CustomPropertySource]:
    return CustomPropertySource.objects.for_team(team_id).filter(
        saved_query_id=binding.id,
        is_enabled=True,
        definition__target_type=TargetType.ACCOUNT.value,
        source_column__isnull=False,
    )


def _enabled_sources(team_id: int, binding: WarehouseBinding) -> list[CustomPropertySource]:
    return list(_enabled_sources_queryset(team_id, binding).select_related("definition"))


def get_account_property_sync_source_ids(team_id: int, binding: WarehouseBinding) -> list[str]:
    source_ids = _enabled_sources_queryset(team_id, binding).order_by("id").values_list("id", flat=True)
    return [str(source_id) for source_id in source_ids]


def _is_source_applicable(source: CustomPropertySource) -> bool:
    return (
        source.is_enabled
        and source.definition.target_type == TargetType.ACCOUNT.value
        and source.source_column is not None
    )


def _parse_source_id(source_id: str) -> UUID:
    try:
        return UUID(source_id)
    except ValueError as error:
        raise AccountPropertySourceRejectedError("Account-property source ID is not a UUID") from error


def _resolve_source(team_id: int, binding: WarehouseBinding, source_id: UUID) -> CustomPropertySource | None:
    sources = CustomPropertySource.objects.for_team(team_id).select_related("definition")
    source = sources.filter(id=source_id, saved_query_id=binding.id).first()
    if source is None and sources.filter(id=source_id).exists():
        raise AccountPropertySourceRejectedError("Account-property source belongs to a different view")
    return source


async def _segment_already_completed(
    team_id: int, binding: WarehouseBinding, job_id: str, segment: AccountPropertySyncSegment
) -> bool:
    marker = f"{account_property_completion_prefix(team_id, binding, job_id)}/{segment.value}.done"
    async with aget_s3_client() as s3_client:
        try:
            await s3_client._cat_file(f"s3://{marker}")
        except FileNotFoundError:
            return False
    return True


def _source_completion_uri(
    team_id: int, binding: WarehouseBinding, job_id: str, segment: AccountPropertySyncSegment, source_id: UUID
) -> str:
    prefix = account_property_completion_prefix(team_id, binding, job_id)
    # Source markers stay in a subdirectory, so the cleanup barrier never reads them as segment markers.
    return f"s3://{prefix}/sources/{segment.value}/{source_id}.done"


async def _read_source_completion(
    team_id: int, binding: WarehouseBinding, job_id: str, segment: AccountPropertySyncSegment, source_id: UUID
) -> dict[str, int] | None:
    async with aget_s3_client() as s3_client:
        try:
            data = await s3_client._cat_file(_source_completion_uri(team_id, binding, job_id, segment, source_id))
        except FileNotFoundError:
            return None
    stored = json.loads(data)
    return {key: int(stored.get(key, 0)) for key in _COUNT_KEYS}


async def _write_source_completion(
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
    source_id: UUID,
    counts: dict[str, int],
) -> None:
    async with aget_s3_client() as s3_client:
        await s3_client._pipe_file(
            _source_completion_uri(team_id, binding, job_id, segment, source_id),
            json.dumps(counts, sort_keys=True).encode("utf-8"),
        )


async def _mark_completed_and_maybe_cleanup(
    team_id: int, binding: WarehouseBinding, job_id: str, segment: AccountPropertySyncSegment
) -> None:
    prefix = account_property_completion_prefix(team_id, binding, job_id)
    async with aget_s3_client() as s3_client:
        await s3_client._pipe_file(f"s3://{prefix}/{segment.value}.done", b"")
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            return
        entries = listing.values() if isinstance(listing, dict) else listing
        completed = {
            entry["Key"].rsplit("/", 1)[-1].removesuffix(".done")
            for entry in entries
            if entry.get("type") != "directory"
        }
        if not _SEGMENTS_REQUIRED_FOR_CLEANUP.issubset(completed):
            return
        try:
            await s3_client._rm(f"s3://{account_property_job_staged_prefix(team_id, binding, job_id)}/", recursive=True)
        except FileNotFoundError:
            pass


async def _load_prior_hashes(
    *,
    team_id: int,
    binding: WarehouseBinding,
    segment: AccountPropertySyncSegment,
    states: list[SourceSyncState],
    log: FilteringBoundLogger,
) -> None:
    phase_started_at = asyncio.get_running_loop().time()
    for state in states:
        state.prior_hashes.update(await _read_snapshot_hashes(team_id, binding, str(state.source.id), segment))
    _record_phase_duration(
        log,
        segment,
        AccountPropertySyncPhase.LOAD_STATE,
        phase_started_at,
        {"source_count": len(states)},
    )


async def _apply_staged_rows(
    *,
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
    states: list[SourceSyncState],
    counts: dict[str, int],
    log: FilteringBoundLogger,
    columns: list[str] | None = None,
    start_batch: int = 0,
    on_batch_applied: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    batch_index = start_batch
    batches = aiter(_iter_parquet_row_batches(team_id, binding, job_id, columns=columns, skip_batches=start_batch))
    while True:
        phase_started_at = asyncio.get_running_loop().time()
        try:
            rows = await anext(batches)
        except StopAsyncIteration:
            break
        _record_phase_duration(
            log,
            segment,
            AccountPropertySyncPhase.READ_STAGED_ROWS,
            phase_started_at,
            {"batch_index": batch_index, "batch_rows": len(rows)},
        )
        counts["rows_read"] += len(rows)
        for state in states:
            state.rows_read += len(rows)
            source = state.source
            source_column = source.source_column
            if source_column is None:
                continue

            phase_started_at = asyncio.get_running_loop().time()
            values_by_external_id = _source_values(rows, source.key_column, source_column)
            changed = {
                external_id: value
                for external_id, value in values_by_external_id.items()
                if state.prior_hashes.get(external_id) != _value_hash(value)
            }
            state.changed += len(changed)
            counts["changed"] += len(changed)
            phase_details: dict[str, bool | float | int | str] = {
                "batch_index": batch_index,
                "source_id": str(source.id),
                "candidate_values": len(values_by_external_id),
                "changed_values": len(changed),
            }
            _record_phase_duration(
                log,
                segment,
                AccountPropertySyncPhase.DIFF_VALUES,
                phase_started_at,
                phase_details,
            )
            if not changed:
                continue

            phase_started_at = asyncio.get_running_loop().time()
            account_ids = await database_sync_to_async(_matching_account_ids, thread_sensitive=False)(
                team_id, segment, list(changed)
            )
            state.matched += len(account_ids)
            counts["matched"] += len(account_ids)
            _record_phase_duration(
                log,
                segment,
                AccountPropertySyncPhase.MATCH_ACCOUNTS,
                phase_started_at,
                {**phase_details, "matched_accounts": len(account_ids)},
            )

            phase_started_at = asyncio.get_running_loop().time()
            applied = await database_sync_to_async(_apply_source_values, thread_sensitive=False)(
                team_id, source, account_ids, changed, segment
            )
            state.written += applied.written
            counts["written"] += applied.written
            if applied.failed:
                state.error = _INVALID_VALUE_ERROR
            state.applied_hashes.update(applied.hashes)
            state.prior_hashes.update(applied.hashes)
            _record_phase_duration(
                log,
                segment,
                AccountPropertySyncPhase.APPLY_VALUES,
                phase_started_at,
                {
                    **phase_details,
                    "matched_accounts": len(account_ids),
                    "written_values": applied.written,
                    "source_failed": applied.failed,
                },
            )
        batch_index += 1
        if on_batch_applied is not None:
            await on_batch_applied(batch_index)


async def _persist_states(
    *,
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
    states: list[SourceSyncState],
    counts: dict[str, int],
    log: FilteringBoundLogger,
) -> None:
    phase_started_at = asyncio.get_running_loop().time()
    persisted_hashes = 0
    for state in states:
        if state.error is not None:
            counts["source_errors"] += 1
        await _write_snapshot_hashes(
            team_id,
            binding,
            str(state.source.id),
            segment,
            job_id,
            state.applied_hashes,
        )
        persisted_hashes += len(state.applied_hashes)
    _record_phase_duration(
        log,
        segment,
        AccountPropertySyncPhase.PERSIST_STATE,
        phase_started_at,
        {"source_count": len(states), "persisted_hashes": persisted_hashes},
    )


def _run_outcome(state: SourceSyncState, error: str | None) -> AccountPropertySyncRunOutcome:
    return AccountPropertySyncRunOutcome(
        source_id=state.source.id,
        rows_read=state.rows_read,
        changed=state.changed,
        matched=state.matched,
        written=state.written,
        error=error,
    )


async def run_account_property_segment_sync(
    *,
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
    final_attempt: bool = False,
) -> dict[str, int]:
    log = logger.bind(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
        segment=segment.value,
    )
    counts = _empty_counts()

    states: list[SourceSyncState] = []
    run_context = AccountPropertySyncRunContext(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
    )

    try:
        if await _segment_already_completed(team_id, binding, job_id, segment):
            return counts

        sources = await database_sync_to_async(_enabled_sources, thread_sensitive=False)(team_id, binding)
        states = [
            SourceSyncState(source=source, prior_hashes={}) for source in sources if source.source_column is not None
        ]
        counts["source_count"] = len(states)
        await _load_prior_hashes(team_id=team_id, binding=binding, segment=segment, states=states, log=log)
        await _apply_staged_rows(
            team_id=team_id, binding=binding, job_id=job_id, segment=segment, states=states, counts=counts, log=log
        )
        await _persist_states(
            team_id=team_id, binding=binding, job_id=job_id, segment=segment, states=states, counts=counts, log=log
        )
    except Exception:
        if final_attempt:
            await database_sync_to_async(finish_account_property_sync_runs)(
                run_context,
                segment,
                [_run_outcome(state, _RUN_FAILED_ERROR) for state in states],
            )
            await database_sync_to_async(finalize_account_property_sync_runs)(
                run_context,
                status=SyncStatus.FAILED,
                phase=SyncPhase.SYNCING,
                error=_RUN_FAILED_ERROR,
                segment=segment,
            )
        raise

    await database_sync_to_async(finish_account_property_sync_runs)(
        run_context,
        segment,
        [_run_outcome(state, state.error) for state in states],
    )
    await database_sync_to_async(finalize_account_property_sync_runs)(
        run_context,
        status=SyncStatus.COMPLETED,
        phase=SyncPhase.COMPLETED,
        segment=segment,
    )

    if counts["source_errors"]:
        raise AccountPropertySourceValueError(
            f"{counts['source_errors']} account-property source(s) contained invalid values",
            counts=counts,
        )

    await _mark_completed_and_maybe_cleanup(team_id, binding, job_id, segment)
    return counts


async def run_account_property_source_sync(
    *,
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
    source_id: str,
    final_attempt: bool = False,
    resume_from: SourceSyncCheckpoint | None = None,
    save_checkpoint: Callable[[SourceSyncCheckpoint], None] | None = None,
) -> dict[str, int]:
    source_uuid = _parse_source_id(source_id)
    log = logger.bind(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
        segment=segment.value,
        source_id=str(source_uuid),
    )
    counts = _empty_counts()
    state: SourceSyncState | None = None
    run_context = AccountPropertySyncRunContext(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
    )

    try:
        if await _segment_already_completed(team_id, binding, job_id, segment):
            return counts
        if await _read_source_completion(team_id, binding, job_id, segment, source_uuid) is not None:
            return counts

        source = await database_sync_to_async(_resolve_source)(team_id, binding, source_uuid)
        if source is None:
            # Deletion cascades to the source's runs, so nothing is left to finish.
            log.warning("Account-property source not found for this team, skipping it")
            return counts

        state = SourceSyncState(source=source, prior_hashes={})
        if _is_source_applicable(source):
            counts["source_count"] = 1
            states = [state]
            start_batch = 0
            if resume_from is not None and not resume_from.matches_mapping(source):
                log.info("Account-property source mapping changed since the checkpoint, restarting the sync")
            elif resume_from is not None:
                resume_from.restore(state, counts)
                start_batch = resume_from.next_batch
                log.info("Resuming account-property source sync from a checkpoint", next_batch=start_batch)
            await _load_prior_hashes(team_id=team_id, binding=binding, segment=segment, states=states, log=log)
            loop = asyncio.get_running_loop()
            last_checkpoint_at = loop.time()
            checkpointed_hashes: dict[str, str] = {}

            async def checkpoint(next_batch: int) -> None:
                nonlocal last_checkpoint_at
                if save_checkpoint is None or loop.time() - last_checkpoint_at < _CHECKPOINT_INTERVAL_SECONDS:
                    return
                new_hashes = {
                    external_id: value_hash
                    for external_id, value_hash in state.applied_hashes.items()
                    if checkpointed_hashes.get(external_id) != value_hash
                }
                await _write_snapshot_delta(
                    team_id, binding, str(source.id), segment, f"{job_id}-checkpoint-{next_batch}", new_hashes
                )
                checkpointed_hashes.update(new_hashes)
                save_checkpoint(SourceSyncCheckpoint.from_state(state, next_batch))
                last_checkpoint_at = loop.time()

            await _apply_staged_rows(
                team_id=team_id,
                binding=binding,
                job_id=job_id,
                segment=segment,
                states=states,
                counts=counts,
                log=log,
                columns=list(
                    dict.fromkeys(column for column in (source.key_column, source.source_column) if column is not None)
                ),
                start_batch=start_batch,
                on_batch_applied=checkpoint,
            )
            await _persist_states(
                team_id=team_id, binding=binding, job_id=job_id, segment=segment, states=states, counts=counts, log=log
            )
        else:
            log.info("Account-property source is no longer eligible, finishing it without changes")
    except AccountPropertySourceRejectedError:
        raise
    except Exception:
        if final_attempt:
            failed_outcome = (
                _run_outcome(state, _RUN_FAILED_ERROR)
                if state is not None
                else AccountPropertySyncRunOutcome(
                    source_id=source_uuid, rows_read=0, changed=0, matched=0, written=0, error=_RUN_FAILED_ERROR
                )
            )
            await database_sync_to_async(finish_account_property_sync_runs)(run_context, segment, [failed_outcome])
        raise

    await database_sync_to_async(finish_account_property_sync_runs)(
        run_context, segment, [_run_outcome(state, state.error)]
    )
    if state.error is not None:
        raise AccountPropertySourceValueError("An account-property source contained invalid values", counts=counts)

    await _write_source_completion(team_id, binding, job_id, segment, source_uuid, counts)
    return counts


async def complete_account_property_sync_segment(
    *,
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
) -> None:
    await database_sync_to_async(complete_account_property_sync_segment_runs)(
        AccountPropertySyncRunContext(team_id=team_id, saved_query_id=binding.id, job_id=job_id),
        segment,
    )
    await _mark_completed_and_maybe_cleanup(team_id, binding, job_id, segment)
