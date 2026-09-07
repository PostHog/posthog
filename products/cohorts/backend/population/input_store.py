"""Retained input for a static cohort population operation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings

from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorage, ObjectStorageError

from products.cohorts.backend.models.cohort import DEFAULT_COHORT_INSERT_BATCH_SIZE

MANIFEST_SCHEMA = 1

SUPPORTED_ID_TYPES = ("distinct_id", "person_id", "email")


class CohortPopulationInputMissing(Exception):
    """The chunk an operation needs to replay is not in storage — expired, reaped, or never written."""


def _prefix(team_id: int, operation_id: UUID | str) -> str:
    return f"{settings.OBJECT_STORAGE_COHORT_POPULATION_FOLDER}/team-{team_id}/{operation_id}"


def _chunk_key(prefix: str, index: int) -> str:
    return f"{prefix}/chunk-{index:06d}.json"


def normalize_identifiers(identifiers: list[str], id_type: str) -> list[str]:
    """Trim, drop blanks, and deduplicate while keeping first-seen order."""
    if id_type not in SUPPORTED_ID_TYPES:
        raise ValueError(f"Unsupported id_type: {id_type}")

    normalize = str.lower if id_type == "email" else lambda value: value
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in identifiers:
        candidate = normalize(raw.strip())
        if candidate and id_type == "person_id":
            candidate = str(UUID(candidate))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def write_input(
    *,
    team_id: int,
    operation_id: UUID | str,
    identifiers: list[str],
    id_type: str,
    chunk_size: int = DEFAULT_COHORT_INSERT_BATCH_SIZE,
) -> dict[str, Any]:
    """Persist normalized identifiers as bounded chunks and return the manifest describing them."""
    normalized = normalize_identifiers(identifiers, id_type)
    prefix = _prefix(team_id, operation_id)

    chunks = [normalized[start : start + chunk_size] for start in range(0, len(normalized), chunk_size)]
    try:
        for index, chunk in enumerate(chunks):
            _write_chunk(_chunk_key(prefix, index), chunk)
    except Exception:
        try:
            object_storage.delete_objects([_chunk_key(prefix, index) for index in range(len(chunks))])
        except Exception:
            pass
        raise

    return {
        "schema": MANIFEST_SCHEMA,
        "prefix": prefix,
        "chunks": len(chunks),
        "total": len(normalized),
        "id_type": id_type,
    }


def append_chunk(manifest: dict[str, Any], identifiers: list[str]) -> dict[str, Any]:
    """Add one more chunk to an existing manifest, returning the updated manifest."""
    normalized = normalize_identifiers(identifiers, manifest["id_type"])
    index = manifest["chunks"]
    # A replaced attempt must never overwrite a page referenced by the current owner's checkpoint.
    key = f"{manifest['prefix']}/page-{uuid4()}.json"
    _write_chunk(key, normalized)
    return {
        **manifest,
        "chunks": index + 1,
        "total": manifest["total"] + len(normalized),
        "chunk_keys": [*manifest.get("chunk_keys", []), key],
    }


def _write_chunk(key: str, identifiers: list[str]) -> None:
    object_storage.write(key, json.dumps(identifiers))
    if object_storage.head_object_strict(key) is None:
        raise ObjectStorageError("Population input was not persisted")


def chunk_key(manifest: dict[str, Any], index: int) -> str:
    return manifest["chunk_keys"][index] if "chunk_keys" in manifest else _chunk_key(manifest["prefix"], index)


def empty_manifest(*, team_id: int, operation_id: UUID | str, id_type: str) -> dict[str, Any]:
    if id_type not in SUPPORTED_ID_TYPES:
        raise ValueError(f"Unsupported id_type: {id_type}")
    return {
        "schema": MANIFEST_SCHEMA,
        "prefix": _prefix(team_id, operation_id),
        "chunks": 0,
        "total": 0,
        "id_type": id_type,
    }


def read_chunk(manifest: dict[str, Any], index: int) -> list[str]:
    """Read one chunk back. Raises ``CohortPopulationInputMissing`` when it is gone."""
    if index >= manifest["chunks"]:
        raise CohortPopulationInputMissing(f"chunk {index} is past the manifest's {manifest['chunks']} chunks")

    raw = object_storage.read(chunk_key(manifest, index), missing_ok=True)
    if raw is None:
        raise CohortPopulationInputMissing(f"chunk {index} of {manifest['prefix']} is no longer in storage")
    return json.loads(raw)


def input_is_readable(manifest: dict[str, Any] | None, *, start: int = 0) -> bool:
    """Whether a retry could still resume from this manifest."""
    if manifest is None:
        return False
    if manifest.get("chunks", 0) == 0:
        return True
    remaining = {chunk_key(manifest, index) for index in range(start, manifest["chunks"])}
    # Listing is paginated; a large upload must not require one HTTP request per retained chunk.
    for key in _input_keys(manifest["prefix"]):
        remaining.discard(key)
        if not remaining:
            return True
    return not remaining


def delete_input(manifest: dict[str, Any] | None) -> None:
    """Remove every chunk. Safe to call twice — a missing object is not an error."""
    if not manifest:
        return
    # Include pages written by an attempt that died before checkpointing its manifest.
    keys: list[str] = []
    for key in _input_keys(manifest["prefix"]):
        keys.append(key)
        if len(keys) == 1000:
            _delete_keys(keys)
            keys = []
    if keys:
        _delete_keys(keys)


def _input_keys(prefix: str) -> Iterator[str]:
    storage = object_storage.object_storage_client()
    if not isinstance(storage, ObjectStorage):
        raise ObjectStorageError("Population input storage is unavailable")
    try:
        pages = storage.aws_client.get_paginator("list_objects_v2").paginate(
            Bucket=settings.OBJECT_STORAGE_BUCKET, Prefix=f"{prefix}/"
        )
        for page in pages:
            yield from (item["Key"] for item in page.get("Contents", []))
    except Exception as error:
        raise ObjectStorageError("Population input listing failed") from error


def _delete_keys(keys: list[str]) -> None:
    if object_storage.delete_objects(keys):
        raise ObjectStorageError("Population input deletion was incomplete")
