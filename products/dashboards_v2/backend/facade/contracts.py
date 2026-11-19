"""
Contract types for dashboards_v2.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


class DashboardV2NotFoundError(LookupError):
    pass


class DashboardV2UidTakenError(Exception):
    def __init__(self, uid: str) -> None:
        super().__init__(f'A dashboard with the uid "{uid}" already exists.')
        self.uid = uid


class DashboardV2VersionConflictError(Exception):
    def __init__(self, *, base_version: int, current_version: int) -> None:
        super().__init__(f"The dashboard is at version {current_version}, not version {base_version}.")
        self.base_version = base_version
        self.current_version = current_version


@dataclass(frozen=True)
class DashboardV2User:
    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: dict[str, Any] | None
    role_at_organization: str | None


@dataclass(frozen=True)
class DashboardV2Summary:
    id: UUID
    uid: str
    title: str
    description: str | None
    folder: str
    tags: list[str]
    version: int
    created_at: datetime
    created_by: DashboardV2User | None
    last_modified_at: datetime
    last_modified_by: DashboardV2User | None


@dataclass(frozen=True)
class DashboardV2Detail(DashboardV2Summary):
    spec: dict[str, Any]


@dataclass(frozen=True)
class CreateDashboardV2Input:
    spec: dict[str, Any]


@dataclass(frozen=True)
class UpdateDashboardV2Input:
    spec: dict[str, Any]
    base_version: int | None = None
    message: str = ""
