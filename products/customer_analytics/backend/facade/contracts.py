"""
Contract types for customer_analytics.

Stable, framework-free frozen dataclasses that define what this product exposes to
the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax and ``is_dataclass()`` compatibility, but with runtime validation on
construction, so structural mistakes from mappers surface at the facade boundary
instead of producing a malformed payload deeper in a caller.
"""

from dataclasses import field
from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class AccountAssignment:
    """A user assigned to an account role (CSM, account executive, account owner)."""

    id: int
    email: str


@dataclass(frozen=True)
class AccountProperties:
    """Typed account properties — assignment roles and external-system identifiers.

    Mirrors ``models.account.AccountProperties`` as a stable, framework-free shape.
    """

    csm: AccountAssignment | None = None
    account_executive: AccountAssignment | None = None
    account_owner: AccountAssignment | None = None
    stripe_customer_id: str | None = None
    hubspot_deal_id: str | None = None
    billing_id: str | None = None
    sfdc_id: str | None = None
    zendesk_id: str | None = None
    slack_channel_id: str | None = None
    usage_dashboard_link: str | None = None


@dataclass(frozen=True)
class Account:
    """A customer-analytics account."""

    id: UUID
    team_id: int
    external_id: str | None
    name: str
    properties: AccountProperties
    created_at: datetime | None


@dataclass(frozen=True)
class AccountRef:
    """Lightweight account reference for search/list result rows.

    ``id`` is the stringified UUID — entity-search rows are emitted as plain dicts
    keyed by string ids.
    """

    id: str
    name: str
    external_id: str | None


@dataclass(frozen=True)
class AccountNote:
    """An internal note (notebook) attached to an account."""

    title: str
    short_id: str


@dataclass(frozen=True)
class AccountContextData:
    """Everything the assistant's account-context formatter renders for one account.

    Bundles the account fields plus the cross-cutting reads (tags, internal notes)
    and the configured account group-type index, so the consumer needs no ORM
    access of its own.
    """

    id: UUID
    name: str
    external_id: str | None
    created_at: datetime | None
    properties: AccountProperties
    tags: list[str] = field(default_factory=list)
    notes: list[AccountNote] = field(default_factory=list)
    account_group_type_index: int | None = None
