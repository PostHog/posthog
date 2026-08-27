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
from datetime import date, datetime
from enum import Enum
from typing import Any, TypedDict
from uuid import UUID

from pydantic.dataclasses import dataclass


class InvalidCustomPropertyOptions(ValueError):
    """Raised when a select property's options fail validation; the viewset maps it to a 400."""


class EventStreamTestMessageError(Exception):
    """The test message could not be sent — unconfigured stream or a Slack API failure."""


@dataclass(frozen=True)
class AccountAssignment:
    """A user assigned to an account relationship (CSM, account executive, ...)."""

    id: int
    email: str


@stdlib_dataclass(frozen=True)
class AccountRelationshipDefinition:
    """A team-defined account relationship type (CSM, Onboarding manager, ...).

    Stdlib dataclass with defaults so the wrapping ``DataclassSerializer`` can construct it
    from partial request bodies (see :class:`CustomPropertyDefinitionView`).
    """

    id: UUID | None = None
    name: str = ""
    description: str | None = None
    is_single_holder: bool = True


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
    """Typed account properties — external-system identifiers.

    Mirrors ``models.account.AccountProperties`` as a stable, framework-free shape.
    """

    website_domain: str | None = None
    stripe_customer_id: str | None = None
    hubspot_deal_id: str | None = None
    billing_id: str | None = None
    sfdc_id: str | None = None
    zendesk_id: str | None = None
    slack_channel_id: str | None = None
    usage_dashboard_link: str | None = None
    metabase_link: str | None = None


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
class EmailAccountMatch:
    account_id: str
    account_external_id: str | None
    match_source: str


@dataclass(frozen=True)
class AccountDueForSlackSummary:
    """An account whose bound Slack channel is due a periodic summary.

    ``period_start``/``period_end`` are the UTC instants of the last closed calendar
    window (yesterday, last ISO week, last month) in the account team's timezone.
    """

    team_id: int
    account_id: str
    account_name: str
    slack_channel_id: str
    cadence: str
    period_start: datetime
    period_end: datetime


@dataclass(frozen=True)
class AccountSlackSummaryBinding:
    """An account's current summary opt-in: its cadence and bound Slack channel."""

    cadence: str
    slack_channel_id: str


@dataclass(frozen=True)
class AccountChannelSummaryView:
    """A stored channel summary as returned by the account summaries endpoint."""

    id: UUID
    slack_channel_id: str
    cadence: str
    period_start: datetime
    period_end: datetime
    content: str
    message_count: int
    # [{author, sent_at, permalink}] per covered message — metadata only, never text.
    messages: list[dict]
    generated_at: datetime


@dataclass(frozen=True)
class CalendarSyncStatus:
    """Sync state of one connected calendar, as shown in settings."""

    integration_id: int
    last_synced_at: datetime | None
    is_syncing: bool


@dataclass(frozen=True)
class MeetingParticipantView:
    """One attendee of a synced calendar meeting."""

    email: str
    display_name: str
    response_status: str
    is_organizer: bool
    person_id: UUID | None


@dataclass(frozen=True)
class MeetingView:
    """A synced calendar meeting as returned by the account meetings endpoint."""

    id: UUID
    title: str
    gong_url: str | None
    start_time: datetime
    end_time: datetime | None
    organizer_email: str
    status: str
    participants: list[MeetingParticipantView]


@dataclass(frozen=True)
class AccountRef:
    """Lightweight account reference for search/list result rows.

    ``id`` is the stringified UUID — entity-search rows are emitted as plain dicts
    keyed by string ids.
    """

    id: str
    name: str
    external_id: str | None


class AccountTableField(str, Enum):
    NAME = "name"
    EXTERNAL_ID = "external_id"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    CHURNED_AT = "churned_at"
    IGNORED_AT = "ignored_at"
    STRIPE_CUSTOMER_ID = "stripe_customer_id"
    HUBSPOT_DEAL_ID = "hubspot_deal_id"
    BILLING_ID = "billing_id"
    SFDC_ID = "sfdc_id"
    ZENDESK_ID = "zendesk_id"


@dataclass(frozen=True, kw_only=True)
class AccountTableColumnSelection:
    account_fields: frozenset[AccountTableField] = frozenset()
    include_tags: bool = False
    include_note_count: bool = False
    relationship_definition_ids: frozenset[UUID] = frozenset()
    custom_property_definition_ids: frozenset[UUID] = frozenset()
    custom_property_history_windows: dict[UUID, int] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class AccountTableSearchFilter:
    query: str


@dataclass(frozen=True, kw_only=True)
class AccountTableTagsFilter:
    tag_names: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class AccountTableAssignedToFilter:
    user_ids: tuple[int, ...]


@dataclass(frozen=True, kw_only=True)
class AccountTableUnassignedFilter:
    pass


@dataclass(frozen=True, kw_only=True)
class AccountTableAccountIdFilter:
    account_id: UUID


class AccountTableFieldOperator(str, Enum):
    EXACT = "exact"
    IS_NOT = "is_not"
    CONTAINS = "icontains"
    DOES_NOT_CONTAIN = "not_icontains"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"
    DATE_EXACT = "is_date_exact"
    DATE_BEFORE = "is_date_before"
    DATE_AFTER = "is_date_after"


@dataclass(frozen=True, kw_only=True)
class AccountTableFieldFilter:
    field: AccountTableField
    operator: AccountTableFieldOperator
    values: tuple[str, ...] = ()


class AccountTableCustomPropertyOperator(str, Enum):
    EXACT = "exact"
    IS_NOT = "is_not"
    CONTAINS = "icontains"
    DOES_NOT_CONTAIN = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"
    DATE_EXACT = "is_date_exact"
    DATE_BEFORE = "is_date_before"
    DATE_AFTER = "is_date_after"


@dataclass(frozen=True, kw_only=True)
class AccountTableCustomPropertyFilter:
    definition_id: UUID
    operator: AccountTableCustomPropertyOperator
    values: tuple[float | bool | str, ...] = ()


AccountTableFilter = (
    AccountTableSearchFilter
    | AccountTableTagsFilter
    | AccountTableAssignedToFilter
    | AccountTableUnassignedFilter
    | AccountTableAccountIdFilter
    | AccountTableFieldFilter
    | AccountTableCustomPropertyFilter
)


class AccountTrackRuleFieldKind(str, Enum):
    ACCOUNT_FIELD = "account_field"
    CUSTOM_PROPERTY = "custom_property"


@dataclass(frozen=True, kw_only=True)
class AccountTrackRuleField:
    kind: AccountTrackRuleFieldKind
    field: AccountTableField | None = None
    definition_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class AccountTrackRuleCondition:
    field: AccountTrackRuleField
    operator: str
    values: tuple[float | bool | str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AccountTrackRuleGroup:
    conditions: tuple[AccountTrackRuleCondition, ...]


@dataclass(frozen=True, kw_only=True)
class AccountTrackRulesConfig:
    schema_version: int = 1
    version: int = 0
    enabled: bool = False
    groups: tuple[AccountTrackRuleGroup, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AccountTrackRuleSample:
    id: UUID
    name: str
    external_id: str | None
    rule_values: dict[str, float | bool | str | None]


@dataclass(frozen=True, kw_only=True)
class AccountTrackRulePreview:
    config_version: int
    eligible_active: int
    skipped_churned: int
    tracked: int
    ignored: int
    newly_ignored: int
    restored: int
    tracked_samples: tuple[AccountTrackRuleSample, ...]
    ignored_samples: tuple[AccountTrackRuleSample, ...]
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AccountTrackRuleRunView:
    id: UUID
    config_version: int
    trigger: str
    status: str
    eligible_active: int
    skipped_churned: int
    tracked: int
    ignored: int
    newly_ignored: int
    restored: int
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    created_by: int | None
    created_at: datetime


class AccountTableSortKind(str, Enum):
    ACCOUNT_FIELD = "account_field"
    TAGS = "tags"
    NOTE_COUNT = "note_count"
    RELATIONSHIP = "relationship"
    CUSTOM_PROPERTY = "custom_property"


class AccountTableSortDirection(str, Enum):
    ASCENDING = "asc"
    DESCENDING = "desc"


@dataclass(frozen=True, kw_only=True)
class AccountTableSort:
    kind: AccountTableSortKind
    direction: AccountTableSortDirection
    account_field: AccountTableField | None = None
    definition_id: UUID | None = None


class AccountTableAggregation(str, Enum):
    SUM = "sum"
    AVERAGE = "avg"
    MINIMUM = "min"
    MAXIMUM = "max"
    MEDIAN = "median"


class AccountTableThresholdOperator(str, Enum):
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "exact"
    NOT_EQUAL = "is_not"


@dataclass(frozen=True, kw_only=True)
class AccountTableCountMetric:
    pass


@dataclass(frozen=True, kw_only=True)
class AccountTableAggregateMetric:
    aggregation: AccountTableAggregation
    definition_id: UUID
    scale: float | None = None


@dataclass(frozen=True, kw_only=True)
class AccountTableCountThresholdMetric:
    definition_id: UUID
    operator: AccountTableThresholdOperator
    value: float


AccountTableMetric = AccountTableCountMetric | AccountTableAggregateMetric | AccountTableCountThresholdMetric


@dataclass(frozen=True, kw_only=True)
class AccountTableCustomPropertyHistoryPoint:
    timestamp: datetime
    value: float


@dataclass(frozen=True, kw_only=True)
class AccountTableRow:
    id: UUID
    name: str
    external_id: str | None
    logo_domain: str | None = None
    account_fields: dict[AccountTableField, str | None] = field(default_factory=dict)
    tags: list[str] | None = None
    note_count: int | None = None
    relationships: dict[UUID, list[int]] = field(default_factory=dict)
    custom_properties: dict[UUID, float | bool | str | None] = field(default_factory=dict)
    custom_property_history: dict[UUID, list[AccountTableCustomPropertyHistoryPoint]] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class AccountTablePage:
    rows: list[AccountTableRow]
    has_more: bool
    limit: int
    offset: int


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
    churned_at: datetime | None
    ignored_at: datetime | None
    properties: AccountProperties
    tags: list[str] = field(default_factory=list)
    notes: list[AccountNote] = field(default_factory=list)
    relationships: list[AccountRelationship] = field(default_factory=list)


@dataclass(frozen=True)
class ExternalAccount:
    """The account shape the external (CDP worker) API serializes verbatim.

    ``properties`` is carried as a plain dict set to exactly
    ``account.properties.model_dump(mode="json")`` — a validated pydantic
    pass-through, not a re-typed projection. ``id`` is the stringified UUID,
    while ``churned_at`` and ``ignored_at`` carry lifecycle timestamps.

    ``custom_properties`` contains every team-defined custom property definition
    keyed by definition name, with the account's current scalar value (or ``None``
    when unset). Every definition is present so result paths are deterministic even
    when a property hasn't been set on this account yet.
    """

    id: str
    external_id: str | None
    name: str
    churned_at: datetime | None
    ignored_at: datetime | None
    properties: dict
    tags: list[str] = field(default_factory=list)
    relationships: dict[str, list[dict]] = field(default_factory=dict)
    custom_properties: dict[str, float | bool | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalAccountAssignment:
    """An active relationship assignment on the external list wire shape.

    Carries the assigned user's id and current email plus their display name so
    external consumers (the billing service's ownership sync) don't need a
    second lookup. ``name`` is None when the user has no name set.
    """

    user_id: int
    email: str
    name: str | None = None


@dataclass(frozen=True)
class ExternalAccountListItem:
    """One account row on the external list wire shape, with its churn timestamp and
    active relationship assignments to current organization members keyed by definition name."""

    external_id: str
    name: str
    churned_at: datetime | None
    ignored_at: datetime | None
    relationships: dict[str, list[ExternalAccountAssignment]] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalAccountListPage:
    """A page of external account rows. ``next_cursor`` is the last account id
    of a full page, or None when the listing is exhausted."""

    results: list[ExternalAccountListItem] = field(default_factory=list)
    next_cursor: str | None = None


class ExternalAccountUpdateError(Enum):
    """Failure modes of the external account write, each mapping to a distinct
    HTTP response in the view."""

    NOT_FOUND = "not_found"
    USER_NOT_IN_ORGANIZATION = "user_not_in_organization"
    RELATIONSHIP_DEFINITION_NOT_FOUND = "relationship_definition_not_found"
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
    slack_summary_cadence: str | None = None
    churned_at: datetime | None = None
    ignored_at: datetime | None = None
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
class FeatureRequestProductAreaView:
    id: UUID | None = None
    name: str = ""
    display_order: int = 0
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class FeatureRequestAccountView:
    id: UUID | None = None
    name: str = ""


@stdlib_dataclass(frozen=True)
class FeatureRequestEvidenceView:
    id: UUID | None = None
    summary: str = ""
    customer_quote: str = ""
    evidence_source: str = "conversation"
    source_url: str = ""
    requested_on: date | None = None
    image_ids: list[UUID] = field(default_factory=list)
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class FeatureRequestAccountLinkView:
    id: UUID | None = None
    account: FeatureRequestAccountView | None = None
    evidence: list[FeatureRequestEvidenceView] = field(default_factory=list)
    evidence_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class FeatureRequestView:
    id: UUID | None = None
    title: str = ""
    description: str = ""
    request_status: str = "requested"
    request_priority: str | None = None
    is_archived: bool = False
    archived_at: datetime | None = None
    archived_by: int | None = None
    version: int = 1
    can_update: bool = False
    account: FeatureRequestAccountView | None = None
    account_links: list[FeatureRequestAccountLinkView] = field(default_factory=list)
    product_areas: list[FeatureRequestProductAreaView] = field(default_factory=list)
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FeatureRequestHistoryChange(TypedDict):
    field: str
    before: object
    after: object


@dataclass(frozen=True)
class FeatureRequestHistoryView:
    id: UUID
    changes: list[FeatureRequestHistoryChange]
    is_initial: bool
    change_source: str
    actor_id: int | None
    actor_name: str | None
    changed_at: datetime


@dataclass(frozen=True)
class FeatureRequestStatusHistoryView:
    id: UUID
    previous_status: str | None
    request_status: str
    change_source: str
    actor_id: int | None
    actor_name: str | None
    changed_at: datetime


@dataclass(frozen=True)
class FeatureRequestListFilters:
    search: str = ""
    statuses: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    product_area_ids: tuple[UUID, ...] = ()
    account_ids: tuple[UUID, ...] = ()
    created_by_ids: tuple[int, ...] = ()
    archive_state: str = "active"
    ordering: str = "-updated_at"


@dataclass(frozen=True)
class FeatureRequestEvidenceInput:
    summary: str
    customer_quote: str
    evidence_source: str
    source_url: str
    requested_on: date | None
    image_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class CreateFeatureRequestInput:
    title: str
    description: str
    account_id: UUID
    product_area_ids: tuple[UUID, ...]
    idempotency_key: UUID
    evidence: FeatureRequestEvidenceInput | None = None


@dataclass(frozen=True)
class FeatureRequestCreateOutcome:
    request: FeatureRequestView
    created: bool


@dataclass(frozen=True)
class UpdateFeatureRequestInput:
    expected_version: int
    title: str | None = None
    description: str | None = None
    account_ids: tuple[UUID, ...] | None = None
    product_area_ids: tuple[UUID, ...] | None = None
    request_status: str | None = None
    request_priority: str | None = None
    request_priority_is_set: bool = False


@dataclass(frozen=True)
class AddFeatureRequestAccountInput:
    expected_version: int
    account_id: UUID
    evidence: FeatureRequestEvidenceInput | None = None


@dataclass(frozen=True)
class CreateFeatureRequestEvidenceInput:
    expected_version: int
    account_link_id: UUID
    summary: str
    customer_quote: str
    evidence_source: str
    source_url: str
    requested_on: date | None
    image_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class UpdateFeatureRequestEvidenceInput:
    expected_version: int
    evidence_id: UUID
    summary: str
    customer_quote: str
    evidence_source: str
    source_url: str
    requested_on: date | None
    image_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True)
class DeleteFeatureRequestEvidenceInput:
    expected_version: int
    evidence_id: UUID


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
    target_type: str = "account"
    # Only set for group targets: which group type (0-4) the property attaches to. Null otherwise.
    group_type_index: int | None = None
    is_big_number: bool = False
    is_canonical: bool = False
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None
    references: list[CustomPropertyReference] = field(default_factory=list)
    source: "CustomPropertySourceView | None" = None
    options: list[CustomPropertyOption] | None = None


@stdlib_dataclass(frozen=True)
class CustomPropertySourceView:
    """A custom-property source: binds warehouse columns to a definition, feeding its values on every
    warehouse run of what it reads.

    ``definition`` / ``saved_query`` / ``external_data_schema`` are ids (the definition this feeds, and
    the warehouse object read from). ``last_sync_error`` is null when the last run succeeded or hasn't
    run. Account-target sources set ``saved_query`` + ``source_column``; person- and group-target
    sources set ``column_property_map`` plus exactly one of ``external_data_schema`` (an imported
    table) and ``saved_query`` (a materialized view). Defaults exist so the wrapping serializer can
    parse partial request bodies (see :class:`AccountView`).
    """

    id: UUID | None = None
    definition: UUID | None = None
    saved_query: UUID | None = None
    external_data_schema: UUID | None = None
    source_column: str | None = ""
    key_column: str = ""
    column_property_map: dict | None = None
    column_descriptions: dict | None = None
    is_enabled: bool = True
    consecutive_failures: int = 0
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None
    # Person/group-target schedule visibility (None for account sources). ``sync_frequency_interval``
    # is in seconds; ``next_sync_at`` is approximate (last run + interval), it drifts if the underlying
    # schedule was paused, and is null for a view whose frequency lives on its DAG node.
    # ``latest_run`` is the most recent sync/backfill run.
    sync_frequency_interval_seconds: float | None = None
    next_sync_at: datetime | None = None
    latest_run: "CustomPropertySyncRunView | None" = None
    # Person/group-target warehouse binding, for naming and linking to what this source reads.
    # ``table_name`` is the imported table as named in HogQL, or the view's name. ``external_data_source``
    # is the warehouse source owning the schema, set only for a table binding; ``saved_query_name`` is
    # set only for a view binding. All None for account sources.
    external_data_source: UUID | None = None
    table_name: str | None = None
    saved_query_name: str | None = None


@stdlib_dataclass(frozen=True)
class CustomPropertySyncRunView:
    """One warehouse-backed custom property sync run."""

    id: UUID | None = None
    job_id: str | None = None
    account_segment: str | None = None
    sync_phase: str | None = None
    attempt: int | None = None
    workflow_id: str | None = None
    workflow_run_id: UUID | None = None
    temporal_url: str | None = None
    trigger: str = ""
    status: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rows_read: int = 0
    changed: int = 0
    existing: int = 0
    produced: int = 0
    skipped_missing_person: int = 0
    error: str | None = None
    created_at: datetime | None = None


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
    slack_summary_cadence: str | None = None
    churned_at: datetime | None = None


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
    slack_summary_cadence: str | None = None
    churned_at: datetime | None = None
    # Distinguishes omitted fields from fields explicitly set to null.
    external_id_provided: bool = False
    properties_provided: bool = False
    slack_summary_cadence_provided: bool = False
    churned_at_provided: bool = False


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


@stdlib_dataclass(frozen=True)
class EventStreamView:
    """A user's event stream as returned by the event-stream endpoints.

    One stream per user per team (``created_by`` is the owner): the events to watch
    (``event_names``), the owner's Slack delivery target, and the member accounts
    (``account_ids``) whose users' events are streamed.
    Defaults exist so the wrapping serializer can parse partial request bodies (see
    :class:`AccountView`).
    """

    id: UUID | None = None
    enabled: bool = False
    event_names: list[str] = field(default_factory=list)
    slack_integration: int | None = None
    slack_channel_id: str = ""
    slack_channel_name: str = ""
    account_ids: list[UUID] = field(default_factory=list)
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None


class AnnouncementValidationError(ValueError):
    def __init__(self, detail: str | dict[str, str]) -> None:
        super().__init__(str(detail))
        self.detail = detail


@stdlib_dataclass(frozen=True)
class AnnouncementChannelView:
    id: str
    name: str
    is_member: bool
    customer_name: str | None


@stdlib_dataclass(frozen=True)
class AnnouncementDeliveryView:
    id: UUID | None = None
    slack_channel_id: str = ""
    slack_channel_name: str = ""
    status: str = ""
    error: str = ""
    slack_message_ts: str = ""
    sent_at: datetime | None = None


@stdlib_dataclass(frozen=True)
class AnnouncementView:
    # Defaults let the wrapping DataclassSerializer parse create requests, which carry only
    # message + channels; channels is write-only and always returned empty.
    id: UUID | None = None
    short_id: str = ""
    message: str = ""
    status: str = ""
    total_channels: int = 0
    sent_count: int = 0
    failed_count: int = 0
    sent_at: datetime | None = None
    created_at: datetime | None = None
    created_by: UserBasicInfo | None = None
    deliveries: list[AnnouncementDeliveryView] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
