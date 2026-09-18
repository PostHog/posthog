"""Observation-time SCD type 2 materialization for saved-query snapshots.

This module contains the policy and comparison layer. Storage and Temporal activities supply the
complete observed rows and persist the returned candidate history.
"""

from __future__ import annotations

import json
import math
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

RESERVED_COLUMNS = frozenset({"valid_from", "valid_to", "_ph_snapshot_version_id"})


class SnapshotValidationError(ValueError):
    pass


class SnapshotPublicationConflict(RuntimeError):
    pass


@dataclass(frozen=True, kw_only=True, slots=True)
class SnapshotConfig:
    unique_key: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.unique_key or any(not isinstance(key, str) or not key for key in self.unique_key):
            raise SnapshotValidationError("A snapshot needs at least one unique-key column.")
        if len(set(self.unique_key)) != len(self.unique_key):
            raise SnapshotValidationError("Snapshot unique-key columns must be distinct.")

    def canonical(self) -> dict[str, Any]:
        return {"unique_key": list(self.unique_key)}


@dataclass(frozen=True, kw_only=True, slots=True)
class SnapshotStats:
    inserted: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    rows_scanned: int = 0


@dataclass(frozen=True, kw_only=True, slots=True)
class SnapshotApplication:
    history: list[dict[str, Any]]
    stats: SnapshotStats


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"__float__": "nan"}
        if math.isinf(value):
            return {"__float__": "-inf" if value < 0 else "inf"}
        return value
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise SnapshotValidationError(f"Unsupported snapshot value type: {type(value).__name__}")


def _key(row: dict[str, Any], config: SnapshotConfig) -> tuple[Any, ...]:
    try:
        values = tuple(row[column] for column in config.unique_key)
    except KeyError as error:
        raise SnapshotValidationError(f"Snapshot key column is missing: {error.args[0]}") from error
    if any(value is None for value in values):
        raise SnapshotValidationError("Snapshot key columns cannot be null.")
    return tuple(json.dumps(_canonical_value(value), sort_keys=True, separators=(",", ":")) for value in values)


def validate_observation(rows: Iterable[dict[str, Any]], config: SnapshotConfig) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    schema: set[str] | None = None
    for row in rows:
        if RESERVED_COLUMNS.intersection(row):
            raise SnapshotValidationError("Query output uses a reserved snapshot column.")
        if schema is None:
            schema = set(row)
        elif set(row) != schema:
            raise SnapshotValidationError("Snapshot query output schema changed within one observation.")
        row_key = _key(row, config)
        if row_key in seen:
            raise SnapshotValidationError("Snapshot unique key is not unique across the complete result.")
        seen.add(row_key)
        result.append(dict(row))
    for key in config.unique_key:
        if schema is not None and key not in schema:
            raise SnapshotValidationError(f"Snapshot key column is missing: {key}")
    return result


def _same_values(previous: dict[str, Any], current: dict[str, Any], config: SnapshotConfig) -> bool:
    columns = set(previous) - RESERVED_COLUMNS - set(config.unique_key)
    return all(
        _canonical_value(previous.get(column)) == _canonical_value(current.get(column)) for column in columns
    ) and all(
        _canonical_value(previous.get(column)) == _canonical_value(current.get(column))
        for column in set(current) - RESERVED_COLUMNS - set(config.unique_key)
    )


def apply_snapshot(
    history: Iterable[dict[str, Any]],
    observed_rows: Iterable[dict[str, Any]],
    *,
    config: SnapshotConfig,
    observed_at: datetime,
    generation: str,
    run_id: str,
) -> SnapshotApplication:
    """Apply one complete observation to a candidate history.

    ``history`` must contain at most one open version for each key. The returned list is a complete
    candidate generation and never mutates the caller's rows.
    """
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    observed_at = observed_at.astimezone(UTC)
    observed = validate_observation(observed_rows, config)
    candidate = [dict(row) for row in history]
    if candidate and observed:
        history_schema = set(candidate[0]) - RESERVED_COLUMNS
        observed_schema = set(observed[0])
        if history_schema != observed_schema:
            raise SnapshotValidationError("Snapshot query output schema changed after initialization.")
    open_versions: dict[tuple[Any, ...], dict[str, Any]] = {}
    latest_observation: datetime | None = None
    for row in candidate:
        valid_from = row.get("valid_from")
        if isinstance(valid_from, datetime):
            latest_observation = max(latest_observation, valid_from) if latest_observation else valid_from
        if row.get("valid_to") is None:
            row_key = _key(row, config)
            if row_key in open_versions:
                raise SnapshotValidationError("History contains more than one open version for a key.")
            open_versions[row_key] = row
    if latest_observation is not None and observed_at <= latest_observation:
        raise SnapshotValidationError("Snapshot observation time must be later than the previous observation.")

    stats = SnapshotStats(rows_scanned=len(observed))
    seen: set[tuple[Any, ...]] = set()
    for row in observed:
        row_key = _key(row, config)
        seen.add(row_key)
        previous = open_versions.get(row_key)
        if previous is not None and _same_values(previous, row, config):
            stats = replace(stats, unchanged=stats.unchanged + 1)
            continue
        if previous is not None:
            previous["valid_to"] = observed_at
            stats = replace(stats, changed=stats.changed + 1)
        else:
            stats = replace(stats, inserted=stats.inserted + 1)
        version = dict(row)
        version["valid_from"] = observed_at
        version["valid_to"] = None
        version["_ph_snapshot_version_id"] = snapshot_version_id(generation, row_key, run_id)
        candidate.append(version)

    for row_key, previous in open_versions.items():
        if row_key not in seen:
            previous["valid_to"] = observed_at
            stats = replace(stats, removed=stats.removed + 1)
    return SnapshotApplication(history=candidate, stats=stats)


def snapshot_version_id(generation: str, key: tuple[Any, ...], run_id: str) -> str:
    payload = json.dumps([generation, key, run_id], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def snapshot_definition_fingerprint(query: dict[str, Any] | None, config: SnapshotConfig) -> str:
    payload = json.dumps({"query": query or {}, "config": config.canonical()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
