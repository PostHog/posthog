"""Canonical form of a check definition, and the fingerprint derived from it.

No Django imports. This is the module a future git-sync would call to project checks into config
files and read them back: the DB stays the source of truth, files are a projection, and
``CheckConfigEntry`` is the shape that round-trips between them without a migration.

The fingerprint is the identity agents author against -- re-creating a semantically identical check
upserts instead of duplicating -- so it must depend only on what the check *asserts*, never on
presentation (name, description, tags, owner). ``subject_uuid`` here is the id of whichever subject
FK the check carries (saved query or table); the file format keeps the loose pair so it stays
portable.
"""

import json
import hashlib
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..facade.enums import CheckSeverity, CheckType, SubjectType


class CheckConfigEntry(BaseModel):
    """A check as a config file would hold it.

    Extras are ignored rather than rejected so this can be built straight from a full check row,
    which carries ids and timestamps a file never would.
    """

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    description: str = ""
    subject_type: SubjectType
    subject_uuid: UUID
    column_name: str = ""
    check_type: CheckType
    config: dict[str, Any] = Field(default_factory=dict)
    severity: CheckSeverity = CheckSeverity.ERROR
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


def to_config_entry(check: dict[str, Any]) -> dict[str, Any]:
    """Project a check into its portable config-file representation."""
    return CheckConfigEntry.model_validate(check).model_dump(mode="json")


def from_config_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Read a config-file entry back into check fields, filling defaults for anything omitted."""
    return CheckConfigEntry.model_validate(entry).model_dump()


def compute_fingerprint(
    *,
    subject_type: str,
    subject_uuid: str,
    check_type: str,
    column_name: str,
    config: dict[str, Any],
) -> str:
    """Hash what the check asserts.

    ``config`` must already be normalized: pass ``spec.validate(...).model_dump(mode="json")``, not
    raw request data. Normalizing through the type's model first means two configs differing only in
    representation (``1`` vs ``1.0``, key order, a stringified number) land on the same fingerprint
    and upsert, instead of quietly creating a near-duplicate check.
    """
    payload = {
        "subject_type": str(subject_type),
        "subject_uuid": str(subject_uuid),
        "check_type": str(check_type),
        "column_name": column_name,
        "config": config,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
