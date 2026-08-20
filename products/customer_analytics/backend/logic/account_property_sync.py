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

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.logic.custom_property_values import (
    InvalidCustomPropertyValue,
    set_synced_custom_property_value,
)
from products.customer_analytics.backend.models import Account, CustomPropertySource, TargetType
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


class AccountPropertySyncSegment(StrEnum):
    TRACKED = "tracked"
    IGNORED = "ignored"


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
    failed: bool = False


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
    *, team_id: int, binding: WarehouseBinding, job_id: str, segment: AccountPropertySyncSegment
) -> dict[str, int]:
    if await _segment_already_completed(team_id, binding, job_id, segment):
        return {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0}

    sources = await database_sync_to_async(_enabled_sources, thread_sensitive=False)(team_id, binding)
    counts = {"rows_read": 0, "changed": 0, "matched": 0, "written": 0, "source_errors": 0}

    states: list[SourceSyncState] = []
    for source in sources:
        if source.source_column is None:
            continue
        states.append(
            SourceSyncState(
                source=source,
                prior_hashes=await _read_snapshot_hashes(team_id, binding, str(source.id), segment),
            )
        )

    async for rows in _iter_parquet_row_batches(team_id, binding, job_id):
        counts["rows_read"] += len(rows)
        for state in states:
            source = state.source
            source_column = source.source_column
            if source_column is None:
                continue
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
            counts["changed"] += len(changed)
            if not changed:
                continue
            account_ids = await database_sync_to_async(_matching_account_ids, thread_sensitive=False)(
                team_id, segment, list(changed)
            )
            counts["matched"] += len(account_ids)
            applied = await database_sync_to_async(_apply_source_values, thread_sensitive=False)(
                team_id, source, account_ids, changed, segment
            )
            counts["written"] += applied.written
            state.failed = state.failed or applied.failed
            state.applied_hashes.update(applied.hashes)
            state.prior_hashes.update(applied.hashes)

    for state in states:
        if state.failed:
            counts["source_errors"] += 1
        await _write_snapshot_hashes(
            team_id,
            binding,
            str(state.source.id),
            segment,
            job_id,
            state.applied_hashes,
        )

    if counts["source_errors"]:
        raise AccountPropertySourceValueError(
            f"{counts['source_errors']} account-property source(s) contained invalid values"
        )

    await _mark_completed_and_maybe_cleanup(team_id, binding, job_id, segment)
    return counts
