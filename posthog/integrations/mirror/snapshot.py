"""The mirror copy of one `posthog_integration` row, read from the primary database.

A row that is gone gives a delete. The GitHub repository cache columns are not mirrored.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import field
from typing import Any

from django.db import DEFAULT_DB_ALIAS

from posthog.dataclasses import frozen
from posthog.integrations.contracts import SOURCE_MARKER_CONFIG_KEY
from posthog.integrations.mirror.canonical import canonical_json
from posthog.integrations.secret_reads import looks_encrypted
from posthog.models.integration.auth_types import effective_auth_type
from posthog.models.integration.model import Integration

# The marker for a `sensitive_config` that is not a JSON object, so no key of it is readable.
ALL_KEYS_UNREADABLE = "__all__"

_MIRRORED_FIELDS = (
    "id",
    "team_id",
    "kind",
    "integration_id",
    "config",
    "sensitive_config",
    "errors",
    "created_by_id",
    "created_at",
    "row_version",
)


@frozen
class MirrorUpsert:
    legacy_id: int
    kind: str
    source_version: int
    integration_id: str | None
    auth_type: str
    is_source_row: bool
    config: Mapping[str, Any]
    sensitive_config: Mapping[str, Any] = field(repr=False)
    legacy_unreadable_keys: tuple[str, ...]
    errors: str
    created_by_id: int | None
    created_at: str

    def to_body(self) -> dict[str, Any]:
        return {
            "legacy_id": self.legacy_id,
            "deleted": False,
            "source_version": self.source_version,
            "kind": self.kind,
            "integration_id": self.integration_id,
            "auth_type": self.auth_type,
            "is_source_row": self.is_source_row,
            "config": dict(self.config),
            "sensitive_config": dict(self.sensitive_config),
            "legacy_unreadable_keys": list(self.legacy_unreadable_keys),
            "errors": self.errors,
            "created_by_id": self.created_by_id,
            "created_at": self.created_at,
        }


@frozen
class MirrorDelete:
    legacy_id: int
    kind: str
    # True stores a deleted row for an unknown legacy id, so a late upsert of it is refused.
    tombstone: bool = True
    source_version: int | None = None

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "legacy_id": self.legacy_id,
            "deleted": True,
            "kind": self.kind,
            "tombstone": self.tombstone,
        }
        if self.source_version is not None:
            body["source_version"] = self.source_version
        return body


MirrorRow = MirrorUpsert | MirrorDelete


class TeamMismatch(Exception):
    """The row with this legacy id belongs to another team."""


class UnmirrorableRow(Exception):
    """The row holds a value that the service cannot store exactly, such as an integer above 2**53."""


def _has_unreadable_leaf(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_has_unreadable_leaf(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_has_unreadable_leaf(item) for item in value)
    return looks_encrypted(value)


def split_unreadable(sensitive_config: object) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The readable top-level keys of `sensitive_config`, and the sorted names of the keys that hold ciphertext."""
    if not isinstance(sensitive_config, Mapping):
        return {}, (ALL_KEYS_UNREADABLE,)
    readable: dict[str, Any] = {}
    unreadable: list[str] = []
    for key, value in sensitive_config.items():
        if _has_unreadable_leaf(value):
            unreadable.append(key)
        else:
            readable[key] = value
    return readable, tuple(sorted(unreadable))


def _iso_timestamp(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat(timespec="microseconds")


def snapshot_of(row: Integration) -> MirrorUpsert:
    config = row.config if isinstance(row.config, dict) else {}
    sensitive_config, unreadable_keys = split_unreadable(row.sensitive_config)
    try:
        # The service parses JSON numbers as doubles, so it would round such an integer without an error.
        canonical_json({"config": config, "sensitive_config": sensitive_config})
    except ValueError as error:
        raise UnmirrorableRow(f"Integration {row.id} holds a value that JSON numbers cannot carry exactly") from error
    return MirrorUpsert(
        legacy_id=row.id,
        kind=row.kind,
        source_version=row.row_version,
        integration_id=row.integration_id,
        auth_type=effective_auth_type(row.kind, config),
        is_source_row=SOURCE_MARKER_CONFIG_KEY in config,
        config=config,
        sensitive_config=sensitive_config,
        legacy_unreadable_keys=unreadable_keys,
        errors=row.errors or "",
        created_by_id=row.created_by_id,
        created_at=_iso_timestamp(row.created_at),
    )


def read_snapshot(*, team_id: int, kind: str, legacy_id: int) -> MirrorRow:
    """The current state of the row in the primary database: an upsert, or a delete when the row is gone."""
    row = Integration._base_manager.using(DEFAULT_DB_ALIAS).only(*_MIRRORED_FIELDS).filter(id=legacy_id).first()
    if row is None:
        return MirrorDelete(legacy_id=legacy_id, kind=kind)
    if row.team_id != team_id:
        # A delete here would leave a tombstone that refuses the real team's copy of the row.
        raise TeamMismatch(f"Integration {legacy_id} does not belong to team {team_id}")
    return snapshot_of(row)
