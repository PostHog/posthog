from __future__ import annotations

from dataclasses import dataclass as stdlib_dataclass
from datetime import datetime
from uuid import UUID


@stdlib_dataclass(frozen=True)
class CustomerTaskUserView:
    id: int
    email: str
    first_name: str
    last_name: str


@stdlib_dataclass(frozen=True)
class CustomerTaskAccountView:
    id: UUID
    name: str


@stdlib_dataclass(frozen=True)
class CustomerTaskView:
    id: UUID
    account: CustomerTaskAccountView | None
    name: str
    description: str | None
    status: str
    assigned_to: CustomerTaskUserView | None
    due_at: datetime | None
    completed_at: datetime | None
    completed_by: CustomerTaskUserView | None
    created_by: CustomerTaskUserView | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    can_edit: bool


@stdlib_dataclass(frozen=True)
class CustomerTaskChange:
    field: str
    before: object | None
    after: object | None


@stdlib_dataclass(frozen=True)
class CustomerTaskActivityView:
    id: UUID
    activity_type: str
    changes: list[CustomerTaskChange]
    actor: CustomerTaskUserView | None
    created_at: datetime


@stdlib_dataclass(frozen=True)
class CustomerTaskListFilters:
    search: str | None = None
    account_id: UUID | None = None
    assigned_to: str | None = None
    statuses: tuple[str, ...] = ()
    archive_state: str = "active"
    due_after: datetime | None = None
    due_before: datetime | None = None
    has_due_at: bool | None = None
    ordering: str | None = None


@stdlib_dataclass(frozen=True)
class CreateCustomerTaskInput:
    account_id: UUID | None = None
    name: str = ""
    description: str | None = None
    assigned_to_id: int | None = None
    due_at: datetime | None = None
    status: str = "open"


@stdlib_dataclass(frozen=True)
class UpdateCustomerTaskInput:
    account_id: UUID | None = None
    name: str | None = None
    description: str | None = None
    assigned_to_id: int | None = None
    due_at: datetime | None = None
    status: str | None = None
    account_id_provided: bool = False
    name_provided: bool = False
    description_provided: bool = False
    assigned_to_id_provided: bool = False
    due_at_provided: bool = False
    status_provided: bool = False
