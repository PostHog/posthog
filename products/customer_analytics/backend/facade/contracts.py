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
from enum import Enum
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

    title: str | None
    short_id: str


@dataclass(frozen=True)
class AccountContextData:
    """The account fields plus cross-cutting reads (tags, internal notes) the
    assistant's account-context formatter renders for one account.

    The configured group-type index stays with the consumer — it reads the core
    ``Team.customer_analytics_config`` property, not product internals.
    """

    id: UUID
    name: str
    external_id: str | None
    created_at: datetime | None
    properties: AccountProperties
    tags: list[str] = field(default_factory=list)
    notes: list[AccountNote] = field(default_factory=list)


@dataclass(frozen=True)
class ExternalAccount:
    """The account shape the external (CDP worker) API serializes verbatim.

    ``properties`` is carried as a plain dict set to exactly
    ``account.properties.model_dump(mode="json")`` so the JSON the CDP worker
    consumes stays byte-identical to the pre-facade response — a validated
    pydantic pass-through, not a re-typed projection. ``id`` is the stringified
    UUID, matching the wire shape.
    """

    id: str
    external_id: str | None
    name: str
    properties: dict
    tags: list[str] = field(default_factory=list)


class ExternalAccountUpdateError(Enum):
    """Failure modes of the external account write, each mapping to a distinct
    HTTP response in the view."""

    NOT_FOUND = "not_found"
    USER_NOT_IN_ORGANIZATION = "user_not_in_organization"
    INVALID_PROPERTIES = "invalid_properties"
    UPDATE_FAILED = "update_failed"


@dataclass(frozen=True)
class ExternalAccountUpdateResult:
    """Outcome of the external account write, modeled so the view can map each
    case to its exact HTTP status and error string without holding write logic.

    Exactly one of ``account`` / ``error`` is set. ``error_field`` carries the
    role field name for a ``USER_NOT_IN_ORGANIZATION`` failure (so the view can
    keep the ``"{field}: ..."`` message shape); it is None otherwise.
    """

    account: ExternalAccount | None = None
    error: ExternalAccountUpdateError | None = None
    error_field: str | None = None
