"""
Contract types for customer_analytics.

Stable, framework-free frozen dataclasses that define what this product exposes to
the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax and ``is_dataclass()`` compatibility, but with runtime validation on
construction, so structural mistakes from mappers surface at the facade boundary
instead of producing a malformed payload deeper in a caller.
"""

from dataclasses import (
    dataclass as stdlib_dataclass,
    field,
)
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class AccountAssignment:
    """A user assigned to an account role (CSM, account executive, account owner)."""

    id: int
    email: str


@dataclass(frozen=True)
class AccountRelationshipDefinition:
    """A team-defined account relationship type (CSM, Onboarding manager, ...)."""

    id: UUID
    name: str
    description: str | None
    is_single_holder: bool


@dataclass(frozen=True)
class AccountRelationship:
    """One assignment of a user to an account relationship, with its effective range."""

    id: UUID
    definition: AccountRelationshipDefinition
    user: AccountAssignment | None
    started_at: datetime
    ended_at: datetime | None


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


# --- Presentation wave: views that back the Accounts CRUD endpoints ---
#
# These contracts shape the DRF responses for the account/customer-journey/
# customer-profile-config viewsets. They are wire-faithful to the pre-isolation
# ``ModelSerializer`` output so the OpenAPI schema (and every downstream generated
# type / MCP tool) stays byte-identical. ``Any`` is used for free-form JSON values
# (account properties, notebook content) so pydantic passes them through verbatim
# rather than coercing.


@stdlib_dataclass(frozen=True)
class UserBasicInfo:
    """Mirror of ``posthog.api.shared.UserBasicSerializer`` output, field-for-field.

    Carries the raw user values (not the rendered representation) so the presentation
    layer can serialize it through the core ``UserBasicSerializer`` — keeping the
    generated ``UserBasic`` OpenAPI component identical. ``hedgehog_config`` stays the
    raw stored value; ``UserBasicSerializer.get_hedgehog_config`` shapes it at render
    time exactly as before.
    """

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: Any
    role_at_organization: str | None


@stdlib_dataclass(frozen=True)
class AccountView:
    """An account as returned by the accounts list/detail endpoints.

    ``properties`` is the raw stored JSON dict (``Account._properties``), not the
    typed :class:`AccountProperties`, so ``exclude_unset`` semantics are preserved —
    an account with no assignments serializes ``properties`` as ``{}`` rather than a
    full object of nulls. ``created_by`` is the creator's user id (or ``None``),
    matching the model serializer's ``PrimaryKeyRelatedField`` output.

    The serializer that wraps this contract is reused as the viewset's
    ``serializer_class`` for both request and response (keeping the OpenAPI ``Account``
    / ``PatchedAccount`` components byte-identical to the old ``ModelSerializer``). To
    let that serializer instantiate the contract from a partial PATCH body, every field
    carries a default — those defaults never reach output (the facade always supplies
    real values) and never relax validation (the serializer pins ``required`` /
    ``read_only`` explicitly).
    """

    id: UUID | None = None
    name: str = ""
    external_id: str | None = None
    properties: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    notebooks: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class CustomerJourneyView:
    """A customer journey as returned by the customer-journey endpoints.

    Defaults exist for the same reason as :class:`AccountView` — the wrapping serializer
    doubles as request + response so the OpenAPI components stay identical.
    """

    id: UUID | None = None
    insight: int = 0
    name: str = ""
    description: str | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class CustomerProfileConfigView:
    """A customer profile config as returned by the profile-config endpoints.

    Defaults exist so the wrapping serializer can parse partial request bodies (see
    :class:`AccountView`).
    """

    id: UUID | None = None
    scope: str = ""
    content: Any = None
    sidebar: Any = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class CustomPropertyReference:
    """A place that uses a custom property definition. ``type`` discriminates the kind of
    referrer (``workflow`` for now); ``id``/``name``/``status`` identify the referring entity."""

    id: str
    name: str
    status: str
    type: str = "workflow"


@stdlib_dataclass(frozen=True)
class CustomPropertyOption:
    """One allowed value of a select custom property. ``id`` is server-assigned and stable across
    renames so option edits can be diffed; ``color`` is a preset data-color token."""

    label: str = ""
    color: str = ""
    id: str | None = None


@stdlib_dataclass(frozen=True)
class CustomPropertyDefinitionView:
    """A team-scoped custom account-property definition as returned by the
    custom-property-definitions endpoints.

    Defaults exist so the wrapping serializer can parse partial request bodies (see
    :class:`AccountView`). ``created_by`` is the creator's user id (or ``None``), matching
    the old model serializer's ``PrimaryKeyRelatedField`` output. ``references`` lists where the
    property is used (workflows), resolved by definition id. ``source`` is the read-only
    view-sync binding when one is configured for this definition, else ``None``.
    """

    id: UUID | None = None
    name: str = ""
    description: str | None = None
    display_type: str = "text"
    is_big_number: bool = False
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None
    references: list[CustomPropertyReference] = field(default_factory=list)
    source: "CustomPropertySourceView | None" = None
    options: list[CustomPropertyOption] | None = None


@stdlib_dataclass(frozen=True)
class CustomPropertySourceView:
    """A custom-property source: binds a materialized view's column to a definition, feeding its
    values on each materialization.

    ``definition`` / ``saved_query`` are ids (the definition this feeds, and the data-warehouse
    saved query read from). ``last_sync_error`` is null when the last run succeeded or hasn't run.
    Defaults exist so the wrapping serializer can parse partial request bodies (see
    :class:`AccountView`).
    """

    id: UUID | None = None
    definition: UUID | None = None
    saved_query: UUID | None = None
    source_column: str = ""
    key_column: str = ""
    is_enabled: bool = True
    consecutive_failures: int = 0
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class AccountNotebookView:
    """An account notebook as returned by the nested account-notebooks endpoints.

    Defaults exist so the wrapping serializer can parse partial request bodies (see
    :class:`AccountView`).
    """

    id: UUID | None = None
    short_id: str = ""
    title: str | None = None
    content: Any = None
    text_content: str | None = None
    created_at: datetime | None = None
    created_by: UserBasicInfo | None = None
    last_modified_at: datetime | None = None
    last_modified_by: UserBasicInfo | None = None


@dataclass(frozen=True)
class AccountNoteView:
    """A row of the team-wide account-notes list: an internal notebook plus the account it's
    linked to. Read-only (the wrapping serializer never parses request bodies), so fields are
    strict — no serializer-instantiation defaults like :class:`AccountView` needs."""

    short_id: str
    title: str | None
    created_at: datetime
    last_modified_at: datetime
    account_id: UUID
    account_name: str
    created_by: UserBasicInfo | None = None


# --- Presentation wave: input contracts for the CRUD write paths ---


@dataclass(frozen=True)
class CreateAccountInput:
    """Validated body for creating an account.

    ``properties`` is the raw client dict; the facade hands it to the model manager,
    which validates it against the pydantic ``AccountProperties`` schema (rejecting
    unknown keys and malformed assignments).
    """

    name: str
    external_id: str | None = None
    properties: dict = field(default_factory=dict)
    tags: list[str] | None = None


@dataclass(frozen=True)
class UpdateAccountInput:
    """Validated partial body for updating an account.

    Each field is optional; only the keys the caller supplied are applied, so a PATCH
    that omits ``name`` leaves the name unchanged. ``tags`` of ``None`` means "tags
    not provided" (left untouched), distinct from ``[]`` (clear all tags).
    """

    name: str | None = None
    external_id: str | None = None
    properties: dict | None = None
    tags: list[str] | None = None
    # Distinguishes "external_id omitted" from "external_id explicitly set to null".
    external_id_provided: bool = False
    properties_provided: bool = False


@dataclass(frozen=True)
class CreateAccountNotebookInput:
    """Validated body for creating an account notebook.

    ``content`` is the ProseMirror document the caller supplied (or ``None``);
    ``synthesized_content`` is the markdown-derived document the view built when the
    caller passed only ``text_content`` — the view owns that normalization so the
    ``ee.hogai`` tiptap helper stays off the facade import path.
    """

    title: str | None
    content: Any
    text_content: str | None
    synthesized_content: Any = None


@dataclass(frozen=True)
class CustomPropertyValue:
    """An account's value for a custom property."""

    id: UUID
    account_id: UUID
    definition_id: UUID
    value: float | bool | str | datetime | None
    created_at: datetime
    created_by_id: int | None


class ExternalAccountCustomPropertiesError(Enum):
    """Failure modes of the external custom-property write, each mapping to a distinct
    HTTP response in the view."""

    ACCOUNT_NOT_FOUND = "account_not_found"
    DEFINITION_NOT_FOUND = "definition_not_found"
    INVALID_VALUE = "invalid_value"
    CONFLICT = "conflict"
    UPDATE_FAILED = "update_failed"
    SOURCE_MANAGED = "source_managed"


@dataclass(frozen=True)
class ExternalAccountCustomPropertiesResult:
    """Outcome of the external custom-property write, modeled so the view can map each
    case to its exact HTTP status and error string without holding write logic.

    Exactly one of ``values`` / ``error`` is set. ``error_field`` carries the offending
    property name for ``DEFINITION_NOT_FOUND`` / ``INVALID_VALUE`` / ``SOURCE_MANAGED`` failures;
    it is None otherwise.
    """

    values: list[CustomPropertyValue] | None = None
    error: ExternalAccountCustomPropertiesError | None = None
    error_field: str | None = None
