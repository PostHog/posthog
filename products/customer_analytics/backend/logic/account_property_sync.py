import io
import json
import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from structlog.typing import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.logic.account_property_coordination import (
    AccountPropertySyncRead,
    get_account_property_snapshot_path,
    get_source_mapping_key,
    guard_account_property_sync_attempt,
    set_account_property_snapshot_path,
    set_coordinated_source_value,
)
from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    AccountPropertySyncRunOutcome,
    finalize_account_property_sync_runs,
    finish_account_property_sync_runs,
)
from products.customer_analytics.backend.logic.custom_property_values import (
    CustomPropertyValueConflict,
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
from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.facade.hooks import WarehouseBinding
from products.warehouse_sources.backend.facade.temporal import (
    account_property_completion_prefix,
    account_property_job_staged_prefix,
    account_property_snapshot_prefix,
)

logger = structlog.get_logger(__name__)

_ACCOUNT_LOOKUP_CHUNK_SIZE = 1_000
_PARQUET_BATCH_SIZE = 50_000
_SEGMENTS_REQUIRED_FOR_CLEANUP = frozenset({"tracked", "ignored"})
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
    pass


@frozen
class AppliedSourceValues:
    written: int
    hashes: dict[str, str]
    failed: bool
    deferred: int = 0


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


async def _iter_parquet_row_batches(
    team_id: int, binding: WarehouseBinding, job_id: str
) -> AsyncIterator[list[dict[str, Any]]]:
    prefix = account_property_job_staged_prefix(team_id, binding, job_id)
    async with aget_s3_client() as s3_client:
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            return
        entries = listing.values() if isinstance(listing, dict) else listing
        file_paths = sorted(entry["Key"] for entry in entries if entry.get("type") != "directory")
        for file_path in file_paths:
            data = await s3_client._cat_file(_s3_uri(file_path))
            batches = await asyncio.to_thread(_parquet_batches, data)
            while (batch := await asyncio.to_thread(next, batches, None)) is not None:
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


async def _write_snapshot_hashes(
    team_id: int,
    binding: WarehouseBinding,
    source_id: str,
    segment: AccountPropertySyncSegment,
    job_id: str,
    hashes: dict[str, str],
) -> None:
    if not hashes:
        return

    prefix = account_property_snapshot_prefix(team_id, binding, source_id, segment.value)
    path = f"{prefix}/{job_id}.parquet"
    async with aget_s3_client() as s3_client:
        existing_files = await _list_snapshot_files(s3_client, prefix)
        merge = await _merge_snapshot_files(s3_client, existing_files)
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


async def _read_coordinated_snapshot_hashes(
    read: AccountPropertySyncRead, source: CustomPropertySource
) -> dict[str, str]:
    path = await database_sync_to_async(get_account_property_snapshot_path, thread_sensitive=False)(read, source)
    if path is None:
        return {}
    async with aget_s3_client() as s3_client:
        merge = await _merge_snapshot_files(s3_client, [path])
    return merge.hashes if merge.complete else {}


async def _write_coordinated_snapshot_hashes(
    read: AccountPropertySyncRead,
    binding: WarehouseBinding,
    source: CustomPropertySource,
    segment: AccountPropertySyncSegment,
    hashes: dict[str, str],
) -> None:
    prefix = account_property_snapshot_prefix(read.team_id, binding, str(source.id), segment.value)
    path = f"{prefix}/coordinated/{get_source_mapping_key(source)}/{read.generation}/{read.token}.parquet"
    snapshot = await asyncio.to_thread(_encode_snapshot, hashes)
    async with aget_s3_client() as s3_client:
        await s3_client._pipe_file(_s3_uri(path), snapshot)
    previous = await database_sync_to_async(set_account_property_snapshot_path, thread_sensitive=False)(
        read, source, path
    )
    if previous is not None:
        try:
            async with aget_s3_client() as s3_client:
                await s3_client._rm(_s3_uri(previous))
        except FileNotFoundError:
            pass
        except Exception as error:
            logger.exception("Account-property snapshot cleanup failed")
            capture_exception(error)


def _finish_segment_runs(
    read: AccountPropertySyncRead | None,
    context: AccountPropertySyncRunContext,
    segment: AccountPropertySyncSegment,
    outcomes: list[AccountPropertySyncRunOutcome],
    *,
    error: str | None = None,
    source_mapping_keys: dict[str, str] | None = None,
) -> None:
    if read is not None:
        with guard_account_property_sync_attempt(read, exclusive=True):
            _finish_segment_runs(None, context, segment, outcomes, error=error, source_mapping_keys=source_mapping_keys)
        return
    finish_account_property_sync_runs(context, segment, outcomes, source_mapping_keys=source_mapping_keys)
    finalize_account_property_sync_runs(
        context,
        status=SyncStatus.FAILED if error else SyncStatus.COMPLETED,
        phase=SyncPhase.SYNCING if error else SyncPhase.COMPLETED,
        error=error,
        segment=segment,
        source_mapping_keys=source_mapping_keys,
    )


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
    sync_read: AccountPropertySyncRead | None = None,
) -> AppliedSourceValues:
    written = 0
    deferred = 0
    applied_hashes: dict[str, str] = {}
    source_failed = False
    for external_id, account_id in account_ids.items():
        value = changed[external_id]
        try:
            if sync_read is not None:
                did_write = set_coordinated_source_value(
                    read=sync_read, source=source, account_id=account_id, value=value
                )
                if did_write is None:
                    continue
            else:
                did_write = set_synced_custom_property_value(
                    team_id=team_id,
                    account_id=account_id,
                    definition=source.definition,
                    value=value,
                )
        except CustomPropertyValueConflict:
            deferred += 1
            continue
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
    return AppliedSourceValues(written=written, hashes=applied_hashes, failed=source_failed, deferred=deferred)


def _enabled_sources(team_id: int, binding: WarehouseBinding) -> list[CustomPropertySource]:
    return list(
        CustomPropertySource.objects.for_team(team_id)
        .select_related("definition")
        .filter(
            saved_query_id=binding.id,
            is_enabled=True,
            definition__target_type=TargetType.ACCOUNT.value,
            source_column__isnull=False,
        )
    )


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


async def run_account_property_segment_sync(
    *,
    team_id: int,
    binding: WarehouseBinding,
    job_id: str,
    segment: AccountPropertySyncSegment,
    final_attempt: bool = False,
    sync_read: AccountPropertySyncRead | None = None,
) -> dict[str, int]:
    log = logger.bind(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
        segment=segment.value,
    )
    counts = {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0}

    states: list[SourceSyncState] = []
    source_mapping_keys: dict[str, str] | None = None
    run_context = AccountPropertySyncRunContext(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
    )

    try:
        if sync_read is None and await _segment_already_completed(team_id, binding, job_id, segment):
            return {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0}

        sources = await database_sync_to_async(_enabled_sources, thread_sensitive=False)(team_id, binding)
        states = [
            SourceSyncState(source=source, prior_hashes={}) for source in sources if source.source_column is not None
        ]
        if sync_read is not None:
            source_mapping_keys = {str(state.source.id): get_source_mapping_key(state.source) for state in states}
        phase_started_at = asyncio.get_running_loop().time()
        for state in states:
            state.prior_hashes.update(
                await _read_coordinated_snapshot_hashes(sync_read, state.source)
                if sync_read is not None
                else await _read_snapshot_hashes(team_id, binding, str(state.source.id), segment)
            )
        _record_phase_duration(
            log,
            segment,
            AccountPropertySyncPhase.LOAD_STATE,
            phase_started_at,
            {"source_count": len(states)},
        )

        batch_index = 0
        batches = aiter(_iter_parquet_row_batches(team_id, binding, job_id))
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
                candidate_values = values_by_external_id if sync_read is not None else changed
                if not candidate_values:
                    continue

                phase_started_at = asyncio.get_running_loop().time()
                account_ids = await database_sync_to_async(_matching_account_ids, thread_sensitive=False)(
                    team_id, segment, list(candidate_values)
                )
                changed_matches = sum(external_id in changed for external_id in account_ids)
                state.matched += changed_matches
                counts["matched"] += changed_matches
                _record_phase_duration(
                    log,
                    segment,
                    AccountPropertySyncPhase.MATCH_ACCOUNTS,
                    phase_started_at,
                    {**phase_details, "matched_accounts": len(account_ids)},
                )

                phase_started_at = asyncio.get_running_loop().time()
                if sync_read is None:
                    applied = await database_sync_to_async(_apply_source_values, thread_sensitive=False)(
                        team_id, source, account_ids, candidate_values, segment
                    )
                else:
                    applied = await database_sync_to_async(_apply_source_values, thread_sensitive=False)(
                        team_id, source, account_ids, candidate_values, segment, sync_read
                    )
                if sync_read is not None and applied.deferred:
                    counts["deferred"] = counts.get("deferred", 0) + applied.deferred
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

        phase_started_at = asyncio.get_running_loop().time()
        persisted_hashes = 0
        for state in states:
            if state.error is not None:
                counts["source_errors"] += 1
            if sync_read is not None:
                await _write_coordinated_snapshot_hashes(sync_read, binding, state.source, segment, state.prior_hashes)
            else:
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
    except Exception:
        if final_attempt:
            await database_sync_to_async(_finish_segment_runs)(
                sync_read,
                run_context,
                segment,
                [
                    AccountPropertySyncRunOutcome(
                        source_id=state.source.id,
                        rows_read=state.rows_read,
                        changed=state.changed,
                        matched=state.matched,
                        written=state.written,
                        error=_RUN_FAILED_ERROR,
                    )
                    for state in states
                ],
                error=_RUN_FAILED_ERROR,
                source_mapping_keys=source_mapping_keys,
            )
        raise

    if counts.get("deferred"):
        return counts

    await database_sync_to_async(_finish_segment_runs)(
        sync_read,
        run_context,
        segment,
        [
            AccountPropertySyncRunOutcome(
                source_id=state.source.id,
                rows_read=state.rows_read,
                changed=state.changed,
                matched=state.matched,
                written=state.written,
                error=state.error,
            )
            for state in states
        ],
        source_mapping_keys=source_mapping_keys,
    )

    if counts["source_errors"]:
        raise AccountPropertySourceValueError(
            f"{counts['source_errors']} account-property source(s) contained invalid values"
        )

    if sync_read is None:
        await _mark_completed_and_maybe_cleanup(team_id, binding, job_id, segment)
    return counts
