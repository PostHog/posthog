from dataclasses import field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from posthog.dataclasses import frozen


class MembershipDeletionKind(StrEnum):
    PERSON = "PERSON"
    TEAM = "TEAM"
    TEAM_PERSONS = "TEAM_PERSONS"


@frozen
class MembershipDeletionInput:
    team_id: int
    receipt_id: UUID


@frozen
class MembershipDeletionReference:
    id: UUID
    team_id: int
    kind: MembershipDeletionKind


@frozen
class MembershipIdentity:
    distinct_id: str = field(repr=False)
    version: int


@frozen
class MembershipDeletionDetails:
    id: UUID
    team_id: int
    kind: MembershipDeletionKind
    source_key: str = field(repr=False)
    person_uuid: UUID | None = field(repr=False)
    person_version: int | None
    created_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None
    confirmed: bool
    completed: bool


@frozen
class MembershipDeletionIdentityRow:
    id: int
    identity: MembershipIdentity


@frozen
class MembershipDeletionIdentityPage:
    identities: tuple[MembershipDeletionIdentityRow, ...]
    next_cursor: int | None


@frozen
class MembershipDeletionCursor:
    created_at: datetime
    id: UUID


@frozen
class MembershipDeletionPage:
    receipts: tuple[MembershipDeletionReference, ...]
    next_cursor: MembershipDeletionCursor | None
