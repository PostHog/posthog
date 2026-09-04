import io
import json
import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import field
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from structlog.typing import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    AccountPropertySyncRunOutcome,
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
            uri = file_path if file_path.startswith("s3://") else f"s3://{file_path}"
            data = await s3_client._cat_file(uri)
            batches = await asyncio.to_thread(_parquet_batches, data)
            while (batch := await asyncio.to_thread(next, batches, None)) is not None:
                yield await asyncio.to_thread(batch.to_pylist)


async def _read_snapshot_hashes(
    team_id: int, binding: WarehouseBinding, source_id: str, segment: AccountPropertySyncSegment
) -> dict[str, str]:
    prefix = account_property_snapshot_prefix(team_id, binding, source_id, segment.value)
    hashes: dict[str, str] = {}
    async with aget_s3_client() as s3_client:
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            return hashes
        entries = listing.values() if isinstance(listing, dict) else listing
        files = sorted(entry["Key"] for entry in entries if entry.get("type") != "directory")
        for file_path in files:
            uri = file_path if file_path.startswith("s3://") else f"s3://{file_path}"
            data = await s3_client._cat_file(uri)
            for row in await asyncio.to_thread(_decode_parquet_rows, data):
                hashes[str(row["external_id"])] = str(row["value_hash"])
    return hashes


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
        try:
            listing = await s3_client._ls(f"s3://{prefix}/", detail=True)
        except FileNotFoundError:
            listing = []
        entries = listing.values() if isinstance(listing, dict) else listing
        existing_files = sorted(entry["Key"] for entry in entries if entry.get("type") != "directory")
        merged: dict[str, str] = {}
        for file_path in existing_files:
            uri = file_path if file_path.startswith("s3://") else f"s3://{file_path}"
            data = await s3_client._cat_file(uri)
            for row in await asyncio.to_thread(_decode_parquet_rows, data):
                merged[str(row["external_id"])] = str(row["value_hash"])
        merged.update(hashes)
        snapshot = await asyncio.to_thread(_encode_snapshot, merged)
        await s3_client._pipe_file(f"s3://{path}", snapshot)
        stale = [file_path for file_path in existing_files if not file_path.endswith(f"/{job_id}.parquet")]
        if stale:
            await s3_client._rm(
                [file_path if file_path.startswith("s3://") else f"s3://{file_path}" for file_path in stale]
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
) -> dict[str, int]:
    log = logger.bind(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
        segment=segment.value,
    )
    counts = {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0}

    states: list[SourceSyncState] = []
    run_context = AccountPropertySyncRunContext(
        team_id=team_id,
        saved_query_id=binding.id,
        job_id=job_id,
    )

    try:
        if await _segment_already_completed(team_id, binding, job_id, segment):
            return {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0}

        sources = await database_sync_to_async(_enabled_sources, thread_sensitive=False)(team_id, binding)
        states = [
            SourceSyncState(source=source, prior_hashes={}) for source in sources if source.source_column is not None
        ]
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
                values_by_external_id: dict[str, Any] = {}
                for row in rows:
                    external_id = row.get(source.key_column)
                    value = row.get(source_column)
                    if external_id is not None and value is not None:
                        values_by_external_id[str(external_id)] = _json_safe(value)
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
    except Exception:
        if final_attempt:
            await database_sync_to_async(finish_account_property_sync_runs)(
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
    )
    await database_sync_to_async(finalize_account_property_sync_runs)(
        run_context,
        status=SyncStatus.COMPLETED,
        phase=SyncPhase.COMPLETED,
        segment=segment,
    )

    if counts["source_errors"]:
        raise AccountPropertySourceValueError(
            f"{counts['source_errors']} account-property source(s) contained invalid values"
        )

    await _mark_completed_and_maybe_cleanup(team_id, binding, job_id, segment)
    return counts
