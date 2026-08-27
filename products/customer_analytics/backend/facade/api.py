"""
Facade API for customer_analytics.

This is the data surface other apps import. Registry/wiring couplings live in
sibling submodules (``queries``, ``max_tools``, ``team_extension``, ``constants``)
to keep this module free of heavy imports (HogQL, ``ee.hogai.tool``) so config-only
consumers don't drag them onto the ``django.setup()`` path.

Responsibilities:
- Read product models, return contracts (never ORM instances or QuerySets)
- Stay thin and stable

Do NOT:
- Implement business rules here (use logic.py)
- Import DRF, serializers, or HTTP concerns
"""

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import (
    Aggregate,
    Avg,
    BooleanField,
    CharField,
    Count,
    DateTimeField,
    Exists,
    F,
    Field,
    FloatField,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    TextField,
    Value,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

import structlog
from celery import current_app
from pydantic import ValidationError as PydanticValidationError
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Integration, OrganizationMembership, Tag
from posthog.models.activity_logging.activity_log import AuditableScope, Detail, Trigger, changes_between, log_activity
from posthog.models.group.util import get_group_by_key
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.tag import tagify
from posthog.models.tagged_item import TaggedItem
from posthog.models.team import Team

from products.conversations.backend.facade.api import (
    AccountEmailThreadMessage as AccountEmailThreadMessage,
    AccountEmailThreadSummary as AccountEmailThreadSummary,
    ConversationMessageSender as ConversationMessageSender,
    ConversationMessageSummary as ConversationMessageSummary,
    EmailThreadAddress as EmailThreadAddress,
    EmailThreadParticipantSummary as EmailThreadParticipantSummary,
    SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured,
    SupportTicketMessage as SupportTicketMessage,
    TicketSummary as TicketSummary,
    list_account_email_thread_messages,
    list_account_email_threads,
    list_account_ticket_messages,
    list_account_tickets,
    trigger_immediate_channel_summary,
)
from products.customer_analytics.backend.account_urls import build_account_deeplink as build_account_deeplink
from products.customer_analytics.backend.events import emit_account_tags_added, emit_account_tags_removed
from products.customer_analytics.backend.facade.contracts import (
    InvalidCustomPropertyOptions as InvalidCustomPropertyOptions,
)
from products.customer_analytics.backend.facade.email_matching import schedule_email_thread_link_recalculation
from products.customer_analytics.backend.logic import (
    account_track_rules as _account_track_rules_logic,
    announcements as _announcements_logic,
    channel_summaries as _channel_summaries_logic,
    custom_property_values as _custom_property_values_logic,
    feature_requests as _feature_requests_logic,
    relationships as _relationships_logic,
)
from products.customer_analytics.backend.logic.account_filters import InvalidAccountFilter, apply_account_filters
from products.customer_analytics.backend.logic.account_logo import resolve_logo_domain
from products.customer_analytics.backend.logic.custom_property_definitions import (
    apply_option_side_effects,
    coerce_is_big_number,
    normalize_options,
)
from products.customer_analytics.backend.logic.custom_property_sync import sync_custom_properties_for_account
from products.customer_analytics.backend.logic.event_stream_destination import (
    archive_event_stream_destination,
    send_test_slack_message as send_test_slack_message,
    sync_event_stream_destination,
    sync_event_stream_destination_by_id as sync_event_stream_destination_by_id,
)
from products.customer_analytics.backend.logic.person_property_projection import (
    person_properties_flag_enabled as person_properties_flag_enabled,
)
from products.customer_analytics.backend.logic.usage_spike_notifications import (
    notify_managers_of_usage_spike as notify_managers_of_usage_spike,
)
from products.customer_analytics.backend.models import (
    CANONICAL_DISPLAY_TYPE_BY_NAME,
    Account,
    AccountChannelSummary,
    AccountRelationship,
    AccountRelationshipDefinition,
    Announcement,
    CustomerJourney,
    CustomerProfileConfig,
    CustomPropertyDefinition,
    CustomPropertySource,
    CustomPropertySyncRun,
    CustomPropertyValue,
    DisplayType,
    EventStream,
    EventStreamMember,
    Meeting,
    SyncStatus,
    SyncTrigger,
    TargetType,
)
from products.customer_analytics.backend.models.account import (
    RETIRED_ROLE_KEYS,
    AccountProperties as _ModelAccountProperties,
)
from products.customer_analytics.backend.models.custom_property_definition import (
    DATA_TYPE_BY_DISPLAY_TYPE,
    NUMERIC_DISPLAY_TYPES,
    DataType,
)
from products.customer_analytics.backend.tasks.tasks import send_announcement
from products.notebooks.backend.facade import (
    api as notebooks,
    contracts as notebook_contracts,
)

# ResourceNotebook stays a direct import for account-list reads because the account relation cannot
# cross a data facade. All account-notebook CRUD goes through `notebooks` (the facade). Tracked by
# the notebooks legacy-leak interface block.
from products.notebooks.backend.models import ResourceNotebook
from products.warehouse_sources.backend.facade.hooks import WarehouseBinding, saved_query_binding, schema_binding
from products.workflows.backend.services.template_input_usage import get_hog_flows_referencing_template_input_keys

from . import contracts

# The "Update account property" workflow action (Hog template) stores the custom property values it
# sets keyed by definition id under its ``properties`` input — the link we resolve into references.
logger = structlog.get_logger(__name__)

_ACCOUNT_PROPERTY_TEMPLATE_ID = "template-posthog-update-account-property"
_ACCOUNT_PROPERTY_INPUT_KEY = "properties"

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.access_control.backend.facade.user_access_control import UserAccessControl
    from products.customer_analytics.backend.models import CustomPropertyValue
    from products.workflows.backend.services.account_audience import AccountAudienceFilters


def _to_account_properties(properties: _ModelAccountProperties) -> contracts.AccountProperties:
    return contracts.AccountProperties(
        website_domain=properties.website_domain,
        stripe_customer_id=properties.stripe_customer_id,
        hubspot_deal_id=properties.hubspot_deal_id,
        billing_id=properties.billing_id,
        sfdc_id=properties.sfdc_id,
        zendesk_id=properties.zendesk_id,
        slack_channel_id=properties.slack_channel_id,
        usage_dashboard_link=properties.usage_dashboard_link,
        metabase_link=properties.metabase_link,
    )


def _to_account_ref(row: dict) -> contracts.AccountRef:
    return contracts.AccountRef(id=str(row["id"]), name=row["name"], external_id=row["external_id"])


def _account_tags(account: Account) -> list[str]:
    return sorted(TaggedItem.objects.filter(account=account).values_list("tag__name", flat=True))


def _account_notes(account: Account) -> list[contracts.AccountNote]:
    return [
        contracts.AccountNote(title=note.title, short_id=note.short_id)
        for note in notebooks.list_account_internal_notes(account.id)
    ]


def get_account_context_data(
    team_id: int,
    account_id: str | None = None,
    external_id: str | None = None,
    *,
    user_access_control: "UserAccessControl",
) -> contracts.AccountContextData | None:
    """Fetch one account (by id or external_id, scoped to the team) with the tags
    and internal notes the assistant context renders, gated by the caller's access.

    Returns None when no account matches, the identifier is malformed, or the caller
    lacks object-level read access — so a denied account is indistinguishable from a
    missing one to the caller.
    """
    account = _resolve_accessible_account(team_id, user_access_control, account_id=account_id, external_id=external_id)
    if account is None:
        return None
    return contracts.AccountContextData(
        id=account.id,
        name=account.name,
        external_id=account.external_id,
        created_at=account.created_at,
        churned_at=account.churned_at,
        ignored_at=account.ignored_at,
        properties=_to_account_properties(account.properties),
        tags=_account_tags(account),
        notes=_account_notes(account),
        relationships=list_account_relationships(team_id=team_id, account_id=account.id),
    )


def _resolve_account(team_id: int, account_id: str | None = None, external_id: str | None = None) -> Account | None:
    try:
        if account_id:
            return Account.objects.for_team(team_id).get(id=account_id)
        if external_id:
            return Account.objects.for_team(team_id).get(external_id=external_id)
        return None
    except (Account.DoesNotExist, ValidationError, ValueError):
        return None


def search_accounts(
    team_id: int,
    query: str,
    user_access_control: "UserAccessControl",
    limit: int,
    *,
    include_ignored: bool = False,
) -> tuple[list[contracts.AccountRef], int]:
    """Accounts matching `query` by name or external id, access-filtered for the caller.

    Returns `(rows, total_count)` where `total_count` is the pre-limit match count.
    """
    queryset = _accounts_queryset(team_id, user_access_control)
    if not include_ignored:
        queryset = queryset.filter(ignored_at__isnull=True)
    queryset = queryset.filter(Q(name__icontains=query) | Q(external_id__icontains=query))
    total_count = queryset.count()
    rows = list(queryset.order_by("name")[:limit].values("id", "name", "external_id"))
    return [_to_account_ref(row) for row in rows], total_count


def list_accounts(
    team_id: int,
    offset: int,
    limit: int,
    user_access_control: "UserAccessControl",
    *,
    include_ignored: bool = False,
) -> tuple[list[contracts.AccountRef], int]:
    """Accounts for the team, newest first, access-filtered for the caller.

    Returns `(rows, total_count)` where `total_count` is the full (unpaginated) count.
    """
    queryset = _accounts_queryset(team_id, user_access_control)
    if not include_ignored:
        queryset = queryset.filter(ignored_at__isnull=True)
    queryset = queryset.order_by("-created_at")
    total_count = queryset.count()
    rows = list(queryset[offset : offset + limit].values("id", "name", "external_id"))
    return [_to_account_ref(row) for row in rows], total_count


def _accounts_queryset(team_id: int, user_access_control: "UserAccessControl"):
    """Base accounts queryset, gated and object-level filtered by the caller's access.

    Account uses a fail-closed manager, so the unscoped manager is used with an
    explicit team filter (mirroring the prior in-consumer behavior).
    """
    if not user_access_control.check_access_level_for_resource("account", "viewer"):
        return Account.objects.unscoped().none()
    return user_access_control.filter_queryset_by_access_level(Account.objects.unscoped().filter(team_id=team_id))


def _resolve_accessible_account(
    team_id: int,
    user_access_control: "UserAccessControl",
    *,
    account_id: str | None = None,
    external_id: str | None = None,
) -> Account | None:
    """Resolve one account the caller is allowed to read, or None.

    Goes through the access-gated queryset so an account the caller can't read is
    returned as None rather than leaked — unlike ``_resolve_account``, which is
    team-scoped only.
    """
    if account_id:
        lookup = {"id": account_id}
    elif external_id:
        lookup = {"external_id": external_id}
    else:
        return None
    try:
        return _accounts_queryset(team_id, user_access_control).filter(**lookup).first()
    except (ValidationError, ValueError):
        return None


def get_account(
    team_id: int, account_id: str | None = None, external_id: str | None = None
) -> contracts.Account | None:
    """Fetch one account (by id or external_id, scoped to the team) as a contract."""
    account = _resolve_account(team_id, account_id=account_id, external_id=external_id)
    if account is None:
        return None
    return contracts.Account(
        id=account.id,
        team_id=account.team_id,
        external_id=account.external_id,
        name=account.name,
        properties=_to_account_properties(account.properties),
        created_at=account.created_at,
    )


def get_account_ref_by_slack_channel_id(team_id: int, slack_channel_id: str) -> contracts.AccountRef | None:
    """Fetch the team's account whose ``slack_channel_id`` property matches the given channel.

    The channel → account mapping is expected to be one-to-one; the property has no
    uniqueness constraint, so if several accounts claim the same channel the mapping is
    ambiguous (an import or config mistake) and attributing to any one of them risks
    tagging tickets with the wrong customer — return None instead.
    """
    if not slack_channel_id:
        return None
    rows = list(
        Account.objects.for_team(team_id)
        .filter(_properties__slack_channel_id=slack_channel_id)
        .values("id", "name", "external_id")[:2]
    )
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "multiple_accounts_claim_slack_channel",
            team_id=team_id,
            slack_channel_id=slack_channel_id,
        )
        return None
    row = rows[0]
    return contracts.AccountRef(id=str(row["id"]), name=row["name"], external_id=row["external_id"])


# --- External (CDP worker) account API ---
#
# The data access, transactional write, org-membership resolution, tag
# application, and exception capture for the Bearer-authed external account
# endpoint. The view keeps only HTTP concerns (auth, throttles, the flag gate,
# request validation) and maps the results below to responses.


def _to_external_account(account: Account) -> contracts.ExternalAccount:
    """Map an account to the verbatim external wire shape.

    ``properties`` is the exact ``model_dump(mode="json")`` of the validated
    pydantic properties, ``tags`` the sorted tag names, and ``churned_at`` the
    account lifecycle timestamp.

    ``custom_properties`` includes every team definition keyed by name, with the
    account's active value (scalar) or ``None`` when unset, so workflow result
    paths are deterministic regardless of whether the property has been set.
    """
    relationships: dict[str, list[dict]] = {}
    for relationship in (
        AccountRelationship.objects.for_team(account.team_id)
        .filter(account=account, ended_at__isnull=True, user__isnull=False)
        .select_related("definition", "user")
        .order_by("definition__name", "user__email")
    ):
        assert relationship.user is not None
        relationships.setdefault(relationship.definition.name, []).append(
            {"user_id": relationship.user.id, "email": relationship.user.email}
        )

    definitions = list(CustomPropertyDefinition.objects.for_team(account.team_id).values("id", "name"))
    active_values = {
        row.definition_id: row
        for row in _custom_property_values_logic.list_active_custom_property_values(
            team_id=account.team_id, account_id=account.id
        )
    }
    custom_properties: dict[str, float | bool | str | None] = {
        defn["name"]: _scalar_value(active_values[defn["id"]]) if defn["id"] in active_values else None
        for defn in definitions
    }

    return contracts.ExternalAccount(
        id=str(account.id),
        external_id=account.external_id,
        name=account.name,
        churned_at=account.churned_at,
        ignored_at=account.ignored_at,
        properties=account.properties.model_dump(mode="json"),
        tags=sorted(account.tagged_items.values_list("tag__name", flat=True)),
        relationships=relationships,
        custom_properties=custom_properties,
    )


def _json_safe_scalar(value: Any) -> float | bool | str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float | bool | str):
        return value
    return None


def _scalar_value(row: "CustomPropertyValue") -> float | bool | str | None:
    """Return the row's value as a JSON-safe scalar; datetimes become ISO strings."""
    return _json_safe_scalar(_custom_property_values_logic.value_of(row))


def _scalar_value_for_display_type(row: "CustomPropertyValue", display_type: DisplayType) -> float | bool | str | None:
    value_column = {
        DataType.STRING: "value_str",
        DataType.NUMERIC: "value_num",
        DataType.BOOLEAN: "value_bool",
        DataType.DATETIME: "value_datetime",
    }[DATA_TYPE_BY_DISPLAY_TYPE[display_type]]
    return _json_safe_scalar(getattr(row, value_column))


def _get_external_account_by_external_id(team_id: int, external_id: str) -> Account | None:
    try:
        return Account.objects.for_team(team_id).select_related("team").get(external_id=external_id)
    except Account.DoesNotExist:
        return None


def get_external_account(team_id: int, external_id: str) -> contracts.ExternalAccount | None:
    """Fetch the team's account by external id for the external API, or None."""
    account = _get_external_account_by_external_id(team_id, external_id)
    if account is None:
        return None
    return _to_external_account(account)


def _account_name_from_group(team: Team, external_id: str) -> str:
    """Resolve the new account's name from its group's ``name`` property, falling back to the
    group key. The name is cosmetic, so a failed lookup must not fail account creation."""
    group_type_index = team.customer_analytics_config.account_group_type_index
    if group_type_index is None:
        return external_id
    try:
        group = get_group_by_key(team.pk, group_type_index, external_id)
    except Exception as e:
        capture_exception(e, {"team_id": team.pk, "external_id": external_id})
        return external_id
    name = (group.group_properties or {}).get("name") if group is not None else None
    return str(name) if name else external_id


def get_account_group_type_name(team: Team) -> str | None:
    """The group type name accounts are keyed on, or None when customer analytics is unconfigured."""
    group_type_index = team.customer_analytics_config.account_group_type_index
    if group_type_index is None:
        return None
    group_types = get_group_types_for_project(team.project_id, caller_tag="customer_analytics/account_audience")
    for mapping in group_types:
        if mapping["group_type_index"] == group_type_index:
            return mapping["group_type"]
    return None


def count_accounts_for_audience(team: Team, filters: "AccountAudienceFilters") -> int:
    from products.customer_analytics.backend.hogql_queries import (  # noqa: PLC0415 — keeps HogQL off the import path
        account_audience,
    )

    return account_audience.count_accounts_for_audience(team, filters)


def list_account_external_ids_for_audience(
    team: Team, filters: "AccountAudienceFilters", *, cursor: str | None, limit: int
) -> list[str]:
    from products.customer_analytics.backend.hogql_queries import (  # noqa: PLC0415 — keeps HogQL off the import path
        account_audience,
    )

    return account_audience.list_account_external_ids_for_audience(team, filters, cursor=cursor, limit=limit)


def create_external_account(
    team: Team, *, external_id: str, workflow_id: str | None = None
) -> tuple[contracts.ExternalAccount, bool]:
    """Get-or-create an account by external id for the external API. Returns the account and
    whether it was created; an existing account is returned untouched. The name comes from the
    matching group's ``name`` property (fallback: the external id). Attribution goes to the
    originating workflow (activity-log trigger) — there is no acting user on this path.
    On workflow-originated creates, warehouse-backed custom properties are synced inline
    (best-effort) so the response already carries them.
    Raises ``AccountPropertiesValidationError`` / ``AccountConflictError`` (concurrent create)."""
    existing = _get_external_account_by_external_id(team.pk, external_id)
    if existing is not None:
        return _to_external_account(existing), False
    trigger = Trigger(job_type="hog_flow", job_id=workflow_id, payload={}) if workflow_id else None
    account = create_account(
        team=team, name=_account_name_from_group(team, external_id), external_id=external_id, trigger=trigger
    )
    if workflow_id is not None:
        # Synchronous so the workflow can read the values in its next step; best-effort inside —
        # a sync failure never fails the creation. Workflow-only to keep the per-request warehouse
        # fan-out off the general create path.
        sync_custom_properties_for_account(team_id=team.pk, external_id=external_id)
    return _to_external_account(account), True


def list_external_accounts(
    team_id: int,
    *,
    organization_id: UUID,
    cursor: str | None = None,
    limit: int = 100,
    assigned_only: bool = False,
    include_ignored: bool = False,
) -> contracts.ExternalAccountListPage:
    """Page through the team's accounts for the external API, ordered by id.

    Account ids are time-ordered UUIDs, so ``id__gt`` is a stable cursor.
    Accounts without an external id are excluded — external consumers key on
    it. Only active relationship assignments to current members of the team's
    organization are exposed. With ``assigned_only``, only accounts holding at
    least one such assignment are returned; a consumer reconciling by absence
    still sees the complete assigned set. Assignments mirror the single-account
    endpoint's ``relationships`` shape (keyed by definition name), with the
    user's current display name added.
    """
    active_relationships = AccountRelationship.objects.for_team(team_id).filter(
        ended_at__isnull=True,
        user__isnull=False,
        user__organization_membership__organization_id=organization_id,
    )
    queryset = Account.objects.for_team(team_id).filter(external_id__isnull=False).exclude(external_id="")
    if not include_ignored:
        queryset = queryset.filter(ignored_at__isnull=True)
    queryset = queryset.order_by("id")
    if assigned_only:
        queryset = queryset.filter(Exists(active_relationships.filter(account=OuterRef("pk"))))
    if cursor:
        queryset = queryset.filter(id__gt=cursor)

    page_accounts = list(queryset[: limit + 1])
    accounts = page_accounts[:limit]

    relationships_by_account: dict[UUID, dict[str, list[contracts.ExternalAccountAssignment]]] = {}
    for relationship in (
        active_relationships.filter(account__in=accounts)
        .select_related("definition", "user")
        .order_by("definition__name", "user__email")
    ):
        user = relationship.user
        assert user is not None
        relationships_by_account.setdefault(relationship.account_id, {}).setdefault(
            relationship.definition.name, []
        ).append(
            contracts.ExternalAccountAssignment(
                user_id=user.id,
                email=user.email,
                name=f"{user.first_name} {user.last_name}".strip() or None,
            )
        )

    results = [
        contracts.ExternalAccountListItem(
            external_id=cast(str, account.external_id),
            name=account.name,
            churned_at=account.churned_at,
            ignored_at=account.ignored_at,
            relationships=relationships_by_account.get(account.id, {}),
        )
        for account in accounts
    ]
    next_cursor = str(accounts[-1].id) if accounts and len(page_accounts) > limit else None
    return contracts.ExternalAccountListPage(results=results, next_cursor=next_cursor)


def _apply_external_tags(account: Account, tags: list[str], mode: str, workflow_id: str | None = None) -> None:
    normalized = list({tagify(t) for t in tags})
    if mode == "remove":
        removed_tags = [
            tagged_item.tag
            for tagged_item in account.tagged_items.filter(tag__name__in=normalized).select_related("tag")
        ]
        account.tagged_items.filter(tag__name__in=normalized).delete()
        _schedule_account_tags_removed(account, removed_tags, actor=None, workflow_id=workflow_id)
    elif mode == "set":
        _set_tags(normalized, account, workflow_id=workflow_id)
    else:
        added_tags: list[Tag] = []
        for tag_name in normalized:
            tag, _ = Tag.objects.get_or_create(name=tag_name, team_id=account.team_id)
            _, created = account.tagged_items.get_or_create(tag_id=tag.id)
            if created:
                added_tags.append(tag)
        _schedule_account_tags_added(account, added_tags, actor=None, workflow_id=workflow_id)


def _apply_external_relationship_assignments(
    account: Account, assignments: dict[str, int | None], workflow_id: str | None = None
) -> contracts.ExternalAccountUpdateResult | None:
    """Apply provided relationship assignments, keyed by definition UUID (None ends the
    active assignment). Each non-None user id is resolved against an
    ``OrganizationMembership`` in the account's org so assignees are always trusted.
    Everything is validated before the first write — the caller's ``atomic()`` block
    returns (commits) on an error result rather than rolling back.
    """
    keys_to_ids: dict[str, UUID] = {}
    for key in assignments:
        try:
            keys_to_ids[key] = UUID(key)
        except ValueError:
            return contracts.ExternalAccountUpdateResult(
                error=contracts.ExternalAccountUpdateError.RELATIONSHIP_DEFINITION_NOT_FOUND,
                error_field=key,
            )

    definitions = {
        definition.id: definition
        for definition in AccountRelationshipDefinition.objects.for_team(account.team_id).filter(
            id__in=keys_to_ids.values()
        )
    }

    resolved: list[tuple[AccountRelationshipDefinition, User | None]] = []
    for key, user_id in assignments.items():
        definition = definitions.get(keys_to_ids[key])
        if definition is None:
            return contracts.ExternalAccountUpdateResult(
                error=contracts.ExternalAccountUpdateError.RELATIONSHIP_DEFINITION_NOT_FOUND,
                error_field=key,
            )
        if user_id is None:
            resolved.append((definition, None))
            continue
        membership = (
            OrganizationMembership.objects.select_related("user")
            .filter(organization_id=account.team.organization_id, user_id=user_id)
            .first()
        )
        if membership is None:
            return contracts.ExternalAccountUpdateResult(
                error=contracts.ExternalAccountUpdateError.USER_NOT_IN_ORGANIZATION,
                error_field=key,
            )
        resolved.append((definition, membership.user))

    for definition, assignee in resolved:
        if assignee is None:
            _relationships_logic.end_active(
                team_id=account.team_id,
                account=account,
                definition=definition,
                workflow_id=workflow_id,
            )
        else:
            _relationships_logic.assign(
                team_id=account.team_id,
                account=account,
                definition=definition,
                user=assignee,
                created_by=None,
                workflow_id=workflow_id,
            )
    return None


def update_external_account(
    team_id: int,
    external_id: str,
    *,
    relationship_assignments: dict[str, int | None],
    tags: list[str] | None,
    tags_mode: str,
    churned_at: datetime | None = None,
    churned_at_provided: bool = False,
    workflow_id: str | None = None,
) -> contracts.ExternalAccountUpdateResult:
    """Apply relationship assignments, tags, and churn state to an account,
    transactionally, for the external API.

    All changes are all-or-nothing — a tag failure must not leave relationship or churn
    changes committed. Returns a result the view maps to the exact HTTP
    status/body: not found, a per-assignment failure (unknown definition, non-member
    user), a generic write failure, or success carrying the re-serialized account.
    """
    account = _get_external_account_by_external_id(team_id, external_id)
    if account is None:
        return contracts.ExternalAccountUpdateResult(error=contracts.ExternalAccountUpdateError.NOT_FOUND)

    # Stored properties are re-serialized onto the success response, so reject accounts
    # whose stored JSON no longer validates before writing anything.
    try:
        _ = account.properties
    except PydanticValidationError:
        return contracts.ExternalAccountUpdateResult(error=contracts.ExternalAccountUpdateError.INVALID_PROPERTIES)

    try:
        with transaction.atomic():
            error_result = _apply_external_relationship_assignments(
                account, relationship_assignments, workflow_id=workflow_id
            )
            if error_result is not None:
                return error_result
            if tags is not None:
                _apply_external_tags(account, tags, tags_mode, workflow_id=workflow_id)
            if churned_at_provided:
                update_account(account, churned_at=churned_at)
    except Exception as e:
        capture_exception(e, {"team_id": team_id, "external_id": external_id, "account_id": str(account.id)})
        return contracts.ExternalAccountUpdateResult(error=contracts.ExternalAccountUpdateError.UPDATE_FAILED)

    account.refresh_from_db()
    return contracts.ExternalAccountUpdateResult(account=_to_external_account(account))


def set_external_account_custom_properties(
    team_id: int,
    external_id: str,
    *,
    properties: dict[str, Any],
    created_by_id: int | None = None,
    workflow_id: str | None = None,
) -> contracts.ExternalAccountCustomPropertiesResult:
    """Set custom property values on an account by definition id, for the external API.

    Resolves the account by external id, then applies every ``{definition_id: value}`` pair
    transactionally — a bad value or unknown definition rolls the whole batch back. Returns a result
    the view maps to the exact HTTP status/body: account not found, unknown definition, invalid
    value, a concurrent-write conflict, a generic write failure, or success carrying the set values.
    """
    account = _get_external_account_by_external_id(team_id, external_id)
    if account is None:
        return contracts.ExternalAccountCustomPropertiesResult(
            error=contracts.ExternalAccountCustomPropertiesError.ACCOUNT_NOT_FOUND
        )

    source_backed = _source_backed_definition_ids(team_id, list(properties.keys()))
    if source_backed:
        return contracts.ExternalAccountCustomPropertiesResult(
            error=contracts.ExternalAccountCustomPropertiesError.SOURCE_MANAGED,
            error_field=str(next(iter(source_backed))),
        )

    try:
        with transaction.atomic():
            rows = _custom_property_values_logic.set_account_custom_properties_by_id(
                team_id=team_id,
                account_id=account.id,
                properties=properties,
                created_by_id=created_by_id,
                workflow_id=workflow_id,
            )
    except _custom_property_values_logic.CustomPropertyDefinitionNotFound as exc:
        return contracts.ExternalAccountCustomPropertiesResult(
            error=contracts.ExternalAccountCustomPropertiesError.DEFINITION_NOT_FOUND,
            error_field=str(exc.identifier),
        )
    except _custom_property_values_logic.InvalidCustomPropertyValue as exc:
        return contracts.ExternalAccountCustomPropertiesResult(
            error=contracts.ExternalAccountCustomPropertiesError.INVALID_VALUE,
            error_field=exc.field,
        )
    except _custom_property_values_logic.CustomPropertyValueConflict:
        return contracts.ExternalAccountCustomPropertiesResult(
            error=contracts.ExternalAccountCustomPropertiesError.CONFLICT
        )
    except Exception as e:
        capture_exception(e, {"team_id": team_id, "external_id": external_id})
        return contracts.ExternalAccountCustomPropertiesResult(
            error=contracts.ExternalAccountCustomPropertiesError.UPDATE_FAILED
        )

    return contracts.ExternalAccountCustomPropertiesResult(values=[_to_custom_property_value(row) for row in rows])


# ---------------------------------------------------------------------------
# Presentation wave: account / customer-journey / profile-config CRUD.
#
# The four DRF viewsets that back the Accounts UI reach their models exclusively
# through the functions below. Everything HTTP — request validation, status
# codes, pagination wiring, permission-mixin gating — stays in the view; the data
# access, transactions, conflict handling, pydantic-error formatting, and the
# activity logging that used to live in ``presentation/views/utils.py`` and the
# ViewSets' ``perform_*`` hooks all live here.
# ---------------------------------------------------------------------------


class AccountConflictError(Exception):
    """Raised when an account write violates the per-team unique external_id constraint."""


class AccountPropertiesValidationError(Exception):
    """Raised when account properties fail the pydantic schema. ``messages`` mirrors the
    field-error list the old serializer produced from ``PydanticValidationError``."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


class CustomerJourneyConflictError(Exception):
    """Raised when a customer journey already exists for the given insight (per team)."""


class CustomPropertyDefinitionConflictError(Exception):
    """Raised when a custom property definition violates the per-team unique name constraint."""


class CanonicalCustomPropertyReadOnlyError(Exception):
    """Raised when an update would change a field PostHog owns on a canonical custom property —
    its name or display type. Both are what the write path matches on, so a user editing them
    would silently stop the values from being recorded (→ 400)."""


class ResourceForbiddenError(Exception):
    """Raised when the caller passes resource/object access checks at the team level but
    lacks the object-level access required for the action — the view maps this to 403,
    matching the ``AccessControlPermission.has_object_permission`` path it replaces."""


class WarehouseSyncPausedError(Exception):
    """Raised when a person-property "sync now" is triggered while the team's warehouse
    syncing is paused (monthly limit reached). The view maps this to 400 with the same
    message the canonical warehouse schema reload/resync endpoints return."""


class ViewNotSyncableError(Exception):
    """Raised when a person-property "sync now" targets a materialized view that can't be
    materialized on demand — it was deleted, or its DAG still runs on the older data-modeling
    schedule, whose workflow never stages person-property rows. The view maps this to 400."""


# Re-export the "not found" exceptions so the view can branch to 404 without importing the
# models. They are model ``DoesNotExist`` subclasses raised by the team-scoped detail fetches.
Account_DoesNotExist = Account.DoesNotExist
CustomerJourney_DoesNotExist = CustomerJourney.DoesNotExist


def _format_pydantic_errors(exc: PydanticValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        messages.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return messages


def _set_tags(
    tags: list[str] | None, account: Account, actor: "User | None" = None, workflow_id: str | None = None
) -> None:
    """Replace the account's tags, creating/deleting ``TaggedItem`` rows individually so
    each change emits its own activity-log entry (the account activity stream depends on
    this).

    Mirrors ``posthog.api.tagged_item.set_tags_on_object`` + ``cleanup_orphan_tags`` but
    stays on pure-model imports so the facade keeps DRF off its import path. ``None`` means
    "tags not supplied" — leave them untouched (matches the serializer mixin).

    Sets ``account.prefetched_tags`` to the resulting rows so a freshly-written account
    renders its new tags without re-reading a stale prefetch (the mixin did the same)."""
    if tags is None:
        return
    deduped_tags = list({tagify(t) for t in tags})
    tagged_item_objects = []
    added_tags: list[Tag] = []
    for tag in deduped_tags:
        tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=account.team_id)
        tagged_item_instance, created = account.tagged_items.get_or_create(tag_id=tag_instance.id)
        tagged_item_instance.tag = tag_instance
        tagged_item_objects.append(tagged_item_instance)
        if created:
            added_tags.append(tag_instance)
    removed_tags: list[Tag] = []
    for tagged_item in account.tagged_items.exclude(tag__name__in=deduped_tags).select_related("tag"):
        removed_tags.append(tagged_item.tag)
        tagged_item.delete()
    Tag.objects.filter(Q(team_id=account.team_id) & Q(tagged_items__isnull=True)).delete()
    account.prefetched_tags = tagged_item_objects  # type: ignore[attr-defined]
    _schedule_account_tags_added(account, added_tags, actor, workflow_id=workflow_id)
    _schedule_account_tags_removed(account, removed_tags, actor, workflow_id=workflow_id)


def _schedule_account_tags_added(
    account: Account, tags: list[Tag], actor: "User | None", workflow_id: str | None = None
) -> None:
    """Emit $account_tag_added after commit for newly created rows only.

    A workflow that adds its trigger tag again must not emit another event.
    """
    if not tags:
        return

    def emit() -> None:
        try:
            emit_account_tags_added(account, tags, actor, workflow_id=workflow_id)
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(emit)


def _schedule_account_tags_removed(
    account: Account, tags: list[Tag], actor: "User | None", workflow_id: str | None = None
) -> None:
    """Emit $account_tag_removed after commit for deleted rows only."""
    if not tags:
        return

    def emit() -> None:
        try:
            emit_account_tags_removed(account, tags, actor, workflow_id=workflow_id)
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(emit)


def _log_activity_swallowing(
    *,
    instance,
    scope: str,
    activity: str,
    name: str,
    organization_id,
    team_id: int,
    user: "User | None",
    was_impersonated: bool,
    previous=None,
    trigger: Trigger | None = None,
) -> None:
    """Replicates ``posthog.api.utils.log_activity_from_viewset`` — including its blanket
    ``except: pass`` — for the account / customer-journey write paths."""
    try:
        detail_kwargs: dict[str, Any] = {"name": name}
        if trigger is not None:
            detail_kwargs["trigger"] = trigger
        if previous is not None:
            detail_kwargs["changes"] = changes_between(cast(AuditableScope, scope), previous=previous, current=instance)
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(instance.id),
            scope=scope,
            activity=activity,
            detail=Detail(**detail_kwargs),
        )
    except Exception:
        pass


# --- CustomerProfileConfig ---


def _to_customer_profile_config_view(config: CustomerProfileConfig) -> contracts.CustomerProfileConfigView:
    return contracts.CustomerProfileConfigView(
        id=config.id,
        scope=config.scope,
        content=config.content,
        sidebar=config.sidebar,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _log_customer_profile_config_activity(
    *,
    instance: CustomerProfileConfig,
    activity: str,
    organization_id,
    team_id: int,
    user: "User",
    was_impersonated: bool,
    previous: Optional[CustomerProfileConfig] = None,
) -> None:
    """Folds in ``presentation/views/utils.log_customer_profile_config_activity`` verbatim
    (note: unlike the account/journey path, this one does NOT swallow exceptions)."""
    name = f"{instance.scope} profile"
    changes = changes_between("CustomerProfileConfig", previous=previous, current=instance)
    log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(instance.id),
        scope="CustomerProfileConfig",
        activity=activity,
        detail=Detail(name=name, changes=changes),
    )


def list_customer_profile_configs(
    team_id: int, offset: int, limit: int
) -> tuple[list[contracts.CustomerProfileConfigView], int]:
    """Profile configs for the team. Returns ``(page, total_count)``."""
    queryset = CustomerProfileConfig.objects.filter(team_id=team_id)
    total_count = queryset.count()
    page = queryset[offset : offset + limit]
    return [_to_customer_profile_config_view(c) for c in page], total_count


def get_customer_profile_config(team_id: int, config_id: str) -> contracts.CustomerProfileConfigView | None:
    config = _get_team_scoped(CustomerProfileConfig, team_id, config_id)
    return _to_customer_profile_config_view(config) if config is not None else None


def create_customer_profile_config(
    *,
    team_id: int,
    scope: str,
    content: Any,
    sidebar: Any,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.CustomerProfileConfigView:
    config = CustomerProfileConfig.objects.create(
        team_id=team_id, created_by=user, scope=scope, content=content, sidebar=sidebar
    )
    _log_customer_profile_config_activity(
        instance=config,
        activity="created",
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    return _to_customer_profile_config_view(config)


def update_customer_profile_config(
    *,
    team_id: int,
    config_id: str,
    fields: dict[str, Any],
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.CustomerProfileConfigView | None:
    """Apply ``fields`` (only the keys the caller sent) to a team-scoped config. Returns the
    updated view, or None when no config matches the id for this team (→ 404 in the view)."""
    config = _get_team_scoped(CustomerProfileConfig, team_id, config_id)
    if config is None:
        return None
    previous = CustomerProfileConfig.objects.get(pk=config.pk)
    for attr, value in fields.items():
        setattr(config, attr, value)
    config.save()
    _log_customer_profile_config_activity(
        instance=config,
        activity="updated",
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        previous=previous,
    )
    return _to_customer_profile_config_view(config)


def delete_customer_profile_config(
    *,
    team_id: int,
    config_id: str,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> bool:
    """Delete a team-scoped config. Returns False when none matched (→ 404)."""
    config = _get_team_scoped(CustomerProfileConfig, team_id, config_id)
    if config is None:
        return False
    instance_id = config.id
    instance_scope = config.scope
    config.delete()
    # Mirror the old viewset: log against a transient instance carrying the deleted id/scope.
    _log_customer_profile_config_activity(
        instance=CustomerProfileConfig(id=instance_id, scope=instance_scope),
        activity="deleted",
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    return True


# --- CustomPropertyDefinition ---


def _to_custom_property_definition_view(
    definition: CustomPropertyDefinition,
    references: list[contracts.CustomPropertyReference] | None = None,
    user_access_control: "UserAccessControl | None" = None,
    enrichment_by_source_id: "dict[Any, tuple[Any, CustomPropertySyncRun | None]] | None" = None,
) -> contracts.CustomPropertyDefinitionView:
    return contracts.CustomPropertyDefinitionView(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        display_type=definition.display_type,
        target_type=definition.target_type,
        group_type_index=definition.group_type_index,
        is_big_number=definition.is_big_number,
        is_canonical=definition.name in CANONICAL_DISPLAY_TYPE_BY_NAME,
        created_at=definition.created_at,
        created_by=definition.created_by_id,
        updated_at=definition.updated_at,
        references=references or [],
        source=_definition_source_view(definition, user_access_control, enrichment_by_source_id),
        options=_to_custom_property_options(definition.options),
    )


def _to_custom_property_options(
    options: list[dict[str, Any]] | None,
) -> list[contracts.CustomPropertyOption] | None:
    if options is None:
        return None
    return [contracts.CustomPropertyOption(**option) for option in options]


def _can_read_workflow_references(user_access_control: "UserAccessControl") -> bool:
    """Whether the caller may see the workflows that reference a custom property.

    ``references`` exposes HogFlow metadata (id, name, status), so it's gated on the caller
    having at least viewer access to the ``hog_flow`` resource — the property-definition API is
    authorized as ``account``, and a caller without workflow read access must not enumerate
    workflows through it. Without RBAC restrictions this resolves to the default (allowed)."""
    return user_access_control.check_access_level_for_resource("hog_flow", "viewer")


def _custom_property_references_by_definition_id(
    team_id: int, definition_id: str | None = None
) -> dict[str, list[contracts.CustomPropertyReference]]:
    """Map each referenced definition id to the workflows that set it via the "Update account
    property" action. One scan of the team's workflows, matched by definition id. Pass
    ``definition_id`` to scan for just that one definition (the single-definition lookup)."""
    usage = get_hog_flows_referencing_template_input_keys(
        team_id, _ACCOUNT_PROPERTY_TEMPLATE_ID, _ACCOUNT_PROPERTY_INPUT_KEY, only_value_key=definition_id
    )
    return {
        referenced_id: [
            contracts.CustomPropertyReference(id=ref.id, name=ref.name, status=ref.status, type="workflow")
            for ref in refs
        ]
        for referenced_id, refs in usage.items()
    }


def _definition_source_view(
    definition: CustomPropertyDefinition,
    user_access_control: "UserAccessControl | None" = None,
    enrichment_by_source_id: "dict[Any, tuple[Any, CustomPropertySyncRun | None]] | None" = None,
) -> contracts.CustomPropertySourceView | None:
    """The source bound to this definition (reverse one-to-one ``source``), or None. List reads
    ``select_related("source")`` so this stays a cache hit; detail reads pay one extra query. Warehouse
    schedule/run enrichment is gated on the caller's warehouse-source viewer access, and batched by the
    list path via ``enrichment_by_source_id`` to avoid per-row queries."""
    try:
        source = definition.source
    except CustomPropertySource.DoesNotExist:
        return None
    enrichment = (
        enrichment_by_source_id.get(source.id, _RESOLVE_ENRICHMENT_INLINE)
        if enrichment_by_source_id is not None
        else _RESOLVE_ENRICHMENT_INLINE
    )
    return _to_custom_property_source_view(source, user_access_control, enrichment)


def list_custom_property_definitions(
    team_id: int,
    offset: int,
    limit: int,
    *,
    user_access_control: "UserAccessControl",
    exclude_group_targets: bool = False,
) -> tuple[list[contracts.CustomPropertyDefinitionView], int]:
    """Custom property definitions for the team, ordered by name. Returns ``(page, total_count)``.

    ``references`` (the workflows referencing each definition) is included only when the caller can
    read workflows — see ``_can_read_workflow_references``. ``exclude_group_targets`` hides group-target
    definitions from callers without ``group`` read authorization."""
    queryset = CustomPropertyDefinition.objects.filter(team_id=team_id).select_related("source").order_by("name")
    if exclude_group_targets:
        queryset = queryset.exclude(target_type=TargetType.GROUP.value)
    total_count = queryset.count()
    page = list(queryset[offset : offset + limit])
    references = (
        _custom_property_references_by_definition_id(team_id)
        if _can_read_workflow_references(user_access_control)
        else {}
    )
    sources: list[CustomPropertySource] = []
    for d in page:
        try:
            sources.append(d.source)
        except CustomPropertySource.DoesNotExist:
            pass
    enrichment = _batch_source_enrichment(team_id, sources, user_access_control)
    return [
        _to_custom_property_definition_view(d, references.get(str(d.id), []), user_access_control, enrichment)
        for d in page
    ], total_count


def get_custom_property_definition(
    team_id: int, definition_id: str, *, user_access_control: "UserAccessControl"
) -> contracts.CustomPropertyDefinitionView | None:
    definition = _get_team_scoped(CustomPropertyDefinition, team_id, definition_id)
    if definition is None:
        return None
    references: list[contracts.CustomPropertyReference] = []
    if _can_read_workflow_references(user_access_control):
        references = _custom_property_references_by_definition_id(team_id, definition_id=str(definition.id)).get(
            str(definition.id), []
        )
    return _to_custom_property_definition_view(definition, references, user_access_control)


def list_custom_property_value_suggestions(team_id: int, definition_id: str, search: str | None) -> list[str]:
    """Suggested filter values for a custom property — see the logic function for the per-type
    behavior. Empty for unknown definitions."""
    return _custom_property_values_logic.list_custom_property_value_suggestions(
        team_id=team_id, definition_id=definition_id, search=search
    )


def create_custom_property_definition(
    *,
    team_id: int,
    name: str,
    description: str | None,
    display_type: str,
    is_big_number: bool,
    options: list[dict[str, Any]] | None = None,
    target_type: str = TargetType.ACCOUNT.value,
    group_type_index: int | None = None,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.CustomPropertyDefinitionView:
    try:
        definition = CustomPropertyDefinition.objects.create(
            team_id=team_id,
            created_by=user,
            name=name,
            description=description,
            display_type=display_type,
            target_type=target_type,
            # Only group targets carry an index; force it null otherwise to satisfy the check constraint.
            group_type_index=group_type_index if target_type == TargetType.GROUP.value else None,
            is_big_number=coerce_is_big_number(display_type, is_big_number),
            options=normalize_options(DisplayType(display_type), options),
        )
    except IntegrityError:
        raise CustomPropertyDefinitionConflictError("A custom property with this name already exists for this team.")
    _log_activity_swallowing(
        instance=definition,
        scope="CustomPropertyDefinition",
        activity="created",
        name=definition.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    return _to_custom_property_definition_view(definition)


def _assert_canonical_fields_unchanged(definition: CustomPropertyDefinition, fields: dict[str, Any]) -> None:
    """Refuse a rename or a type change on a canonical property — PostHog owns both.

    Everything else on the definition (description, position in a view) stays editable. Deleting
    it is allowed: the next recorded value recreates it.
    """
    if definition.name not in CANONICAL_DISPLAY_TYPE_BY_NAME:
        return
    for attr in ("name", "display_type"):
        if attr in fields and fields[attr] != getattr(definition, attr):
            raise CanonicalCustomPropertyReadOnlyError(
                f"'{definition.name}' is set by PostHog, so its {attr.replace('_', ' ')} can't be changed."
            )


def update_custom_property_definition(
    *,
    team_id: int,
    definition_id: str,
    fields: dict[str, Any],
    organization_id,
    user: "User",
    was_impersonated: bool,
    user_access_control: "UserAccessControl | None" = None,
) -> contracts.CustomPropertyDefinitionView | None:
    """Apply ``fields`` (only the keys the caller sent) to a team-scoped definition. Returns the
    updated view, or None when no definition matches the id for this team (→ 404)."""
    definition = _get_team_scoped(CustomPropertyDefinition, team_id, definition_id)
    if definition is None:
        return None
    _assert_canonical_fields_unchanged(definition, fields)
    previous = CustomPropertyDefinition.objects.get(pk=definition.pk)
    for attr, value in fields.items():
        setattr(definition, attr, value)
    # Re-coerce against the effective display type: a PATCH that only flips the type to a
    # non-numeric one must clear a previously-set is_big_number (the partial-update case).
    definition.is_big_number = coerce_is_big_number(definition.display_type, definition.is_big_number)
    definition.options = normalize_options(
        DisplayType(definition.display_type),
        definition.options,
        existing_ids=frozenset(option["id"] for option in previous.options or []),
    )
    try:
        with transaction.atomic():
            definition.save()
            if DisplayType(definition.display_type) == DisplayType.SELECT:
                apply_option_side_effects(
                    team_id=team_id,
                    definition_id=definition.id,
                    previous_options=previous.options,
                    new_options=definition.options,
                )
    except IntegrityError:
        raise CustomPropertyDefinitionConflictError("A custom property with this name already exists for this team.")
    _log_activity_swallowing(
        instance=definition,
        scope="CustomPropertyDefinition",
        activity="updated",
        name=definition.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        previous=previous,
    )
    return _to_custom_property_definition_view(definition, user_access_control=user_access_control)


def delete_custom_property_definition(
    *,
    team_id: int,
    definition_id: str,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> bool:
    """Delete a team-scoped definition. Returns False when none matched (→ 404)."""
    definition = _get_team_scoped(CustomPropertyDefinition, team_id, definition_id)
    if definition is None:
        return False
    _log_activity_swallowing(
        instance=definition,
        scope="CustomPropertyDefinition",
        activity="deleted",
        name=definition.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    definition.delete()
    return True


# --- CustomPropertySource ---


class CustomPropertySourceValidationError(Exception):
    """Raised when a source's saved_query isn't a usable view for the team, or the definition is
    already source-backed (→ 400)."""


def _temporal_run_url(run: "CustomPropertySyncRun") -> str | None:
    if not run.workflow_id or not run.workflow_run_id:
        return None
    base = settings.TEMPORAL_UI_HOST
    namespace = settings.TEMPORAL_NAMESPACE
    if not base or not namespace:
        return None
    return f"{base.rstrip('/')}/namespaces/{namespace}/workflows/{run.workflow_id}/{run.workflow_run_id}"


def _to_sync_run_view(
    run: "CustomPropertySyncRun", *, include_temporal_url: bool = False
) -> contracts.CustomPropertySyncRunView:
    return contracts.CustomPropertySyncRunView(
        id=run.id,
        job_id=run.job_id,
        account_segment=run.segment,
        sync_phase=run.phase,
        attempt=run.attempt,
        workflow_id=run.workflow_id if include_temporal_url else None,
        workflow_run_id=run.workflow_run_id if include_temporal_url else None,
        temporal_url=_temporal_run_url(run) if include_temporal_url else None,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        rows_read=run.rows_read,
        changed=run.changed,
        existing=run.existing,
        produced=run.produced,
        skipped_missing_person=run.skipped_missing_person,
        error=run.error,
        created_at=run.created_at,
    )


@frozen
class _ProfileWarehouseMeta:
    """Display metadata a profile source derives from the warehouse object it reads.

    Resolved for both binding kinds so the view builder doesn't branch on kind. ``external_data_source``
    is set only for a schema binding (a view has no import source), ``saved_query_name`` only for a view.
    """

    table_name: str
    sync_frequency_interval_seconds: float | None = None
    next_sync_at: datetime | None = None
    external_data_source: UUID | None = None
    saved_query_name: str | None = None


def _profile_binding(source: CustomPropertySource) -> "WarehouseBinding | None":
    """The warehouse object a person/group-target source reads, or None for an account source.

    Reads ``definition.target_type`` rather than inferring from which column is set: an account source
    is also bound to a saved query, so the binding column alone no longer tells the two apart. Callers
    pass a source with its definition selected.
    """
    if source.definition.target_type not in _WAREHOUSE_PROFILE_TARGETS:
        return None
    if source.saved_query_id is not None:
        return saved_query_binding(source.saved_query_id)
    if source.external_data_schema_id is not None:
        return schema_binding(source.external_data_schema_id)
    return None


def _resolve_schema(team_id: int, schema_id: Any, user_access_control: "UserAccessControl | None") -> Any:
    """The ``ExternalDataSchema`` (with ``.source`` loaded) for a schema-bound source, or None when it
    no longer exists or the caller lacks object-level ``external_data_source`` viewer access.
    ``user_access_control`` None (service auth) skips the object check, matching ``_enforce_object_access``.
    ``apps.get_model`` keeps this off a warehouse_sources internal import."""
    schema_model = apps.get_model("warehouse_sources", "ExternalDataSchema")
    schema = schema_model.objects.filter(id=schema_id, team_id=team_id).select_related("source", "table").first()
    if schema is None:
        return None
    if user_access_control is not None and not user_access_control.check_access_level_for_object(
        schema.source, required_level="viewer"
    ):
        return None
    return schema


def _resolve_saved_query(team_id: int, saved_query_id: Any, user_access_control: "UserAccessControl | None") -> Any:
    """The ``DataWarehouseSavedQuery`` for a view-bound source, or None when it no longer resolves or
    the caller lacks object-level ``warehouse_view`` viewer access — the same gate the warehouse view
    endpoints and HogQL resolution apply."""
    saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    saved_query = saved_query_model.objects.filter(id=saved_query_id, team_id=team_id).exclude(deleted=True).first()
    if saved_query is None:
        return None
    if user_access_control is not None and not user_access_control.check_access_level_for_object(
        saved_query, required_level="viewer"
    ):
        return None
    return saved_query


def _saved_query_meta(saved_query: Any) -> _ProfileWarehouseMeta:
    """Display metadata for a view-bound source. A view's name is already its HogQL name, so it needs
    no table-name resolution. ``sync_frequency_interval`` is null once the view's DAG runs on a shared
    schedule (the frequency lives on the DAG node), which leaves the next run unknown rather than
    guessable — so both schedule fields stay None."""
    interval = saved_query.sync_frequency_interval
    next_sync_at = (
        saved_query.last_run_at + interval if interval is not None and saved_query.last_run_at is not None else None
    )
    return _ProfileWarehouseMeta(
        table_name=saved_query.name,
        sync_frequency_interval_seconds=interval.total_seconds() if interval is not None else None,
        next_sync_at=next_sync_at,
        saved_query_name=saved_query.name,
    )


def _resolve_profile_warehouse_meta(
    source: CustomPropertySource, user_access_control: "UserAccessControl | None"
) -> _ProfileWarehouseMeta | None:
    """Warehouse-derived display metadata for a profile source, or None for an account source, a
    warehouse object that no longer exists, or a caller without viewer access to it."""
    binding = _profile_binding(source)
    if binding is None:
        return None
    if binding.is_saved_query:
        saved_query = _resolve_saved_query(source.team_id, binding.id, user_access_control)
        return _saved_query_meta(saved_query) if saved_query is not None else None
    schema = _resolve_schema(source.team_id, binding.id, user_access_control)
    return _schema_meta(schema) if schema is not None else None


def _schema_table_name(schema: Any) -> str:
    """The bound table as it is named in HogQL, so the UI shows the name the table picker offered.
    Falls back to the schema name when the first sync hasn't created the table yet. The HogQL import
    is deferred to keep the heavy database module off this module's import path."""
    from posthog.hogql.database.database import (
        get_data_warehouse_table_name,  # noqa: PLC0415 — keeps HogQL off the import path
    )

    if schema.table_id is None:
        return schema.name
    return get_data_warehouse_table_name(schema.source, schema.table.name)


def _schema_meta(schema: Any) -> _ProfileWarehouseMeta:
    """Display metadata for a schema-bound source. Both schedule fields stay None when the schema has
    no sync frequency configured."""
    interval = schema.sync_frequency_interval
    next_sync_at = (
        schema.last_synced_at + interval if interval is not None and schema.last_synced_at is not None else None
    )
    return _ProfileWarehouseMeta(
        table_name=_schema_table_name(schema),
        sync_frequency_interval_seconds=interval.total_seconds() if interval is not None else None,
        next_sync_at=next_sync_at,
        external_data_source=schema.source_id,
    )


# Sentinel so a caller can pass a prefetched (schema, latest_run) pair — including ``(None, None)``
# for a person source the caller can't see — distinct from "resolve inline" (the detail path).
class _ResolveEnrichmentInline:
    pass


_RESOLVE_ENRICHMENT_INLINE = _ResolveEnrichmentInline()


def _to_custom_property_source_view(
    source: CustomPropertySource,
    user_access_control: "UserAccessControl | None" = None,
    enrichment: "tuple[_ProfileWarehouseMeta | None, CustomPropertySyncRun | None] | _ResolveEnrichmentInline" = _RESOLVE_ENRICHMENT_INLINE,
) -> contracts.CustomPropertySourceView:
    # Schedule + latest-run enrichment applies only to person/group sources; account sources leave it
    # None. The enrichment exposes the underlying warehouse object's schedule and run metadata, so it's
    # gated on the caller's viewer access to that object — a caller without it sees the source but not
    # its warehouse-derived metadata. ``enrichment`` lets list endpoints prefetch the metadata + latest
    # run in one batched query each (see ``_batch_source_enrichment``) instead of two per row.
    latest_run: contracts.CustomPropertySyncRunView | None = None
    if isinstance(enrichment, _ResolveEnrichmentInline):
        meta = _resolve_profile_warehouse_meta(source, user_access_control)
        latest = source.sync_runs.order_by("-created_at").first() if meta is not None else None
        _expire_stale_running_runs(source.team_id, [latest])
    else:
        meta, latest = enrichment
    if meta is not None:
        latest_run = _to_sync_run_view(latest) if latest is not None else None

    # A profile source's sync status (raw error text, failure streak, last-synced time) is produced by
    # the underlying warehouse object, so it's warehouse-derived metadata gated the same way as the
    # schedule/latest-run above — a caller without viewer access on that object sees the mapping but not
    # its status. Column descriptions are likewise warehouse-derived (populated from the object's
    # ``information_schema.columns`` or set by a warehouse editor), so they're gated the same way.
    # Account sources are not warehouse-gated; their status and descriptions stay visible.
    warehouse_status_visible = _profile_binding(source) is None or meta is not None

    return contracts.CustomPropertySourceView(
        id=source.id,
        definition=source.definition_id,
        saved_query=source.saved_query_id,
        external_data_schema=source.external_data_schema_id,
        source_column=source.source_column,
        key_column=source.key_column,
        column_property_map=source.column_property_map,
        column_descriptions=source.column_descriptions if warehouse_status_visible else {},
        is_enabled=source.is_enabled,
        consecutive_failures=source.consecutive_failures if warehouse_status_visible else 0,
        last_synced_at=source.last_synced_at if warehouse_status_visible else None,
        last_sync_error=source.last_sync_error if warehouse_status_visible else None,
        created_at=source.created_at,
        created_by=source.created_by_id,
        updated_at=source.updated_at,
        sync_frequency_interval_seconds=meta.sync_frequency_interval_seconds if meta else None,
        next_sync_at=meta.next_sync_at if meta else None,
        latest_run=latest_run,
        external_data_source=meta.external_data_source if meta else None,
        table_name=meta.table_name if meta else None,
        saved_query_name=meta.saved_query_name if meta else None,
    )


def _batch_source_enrichment(
    team_id: int, sources: list[CustomPropertySource], user_access_control: "UserAccessControl | None"
) -> dict[Any, "tuple[_ProfileWarehouseMeta | None, CustomPropertySyncRun | None]"]:
    """Resolve the warehouse metadata (with viewer access applied) and latest run for a page of profile
    sources in one query per warehouse kind, so a list endpoint doesn't issue two per-row queries (see
    the per-row path in ``_to_custom_property_source_view``). Returns
    ``{source_id: (meta_or_None, latest_run)}``; account sources are absent, so they resolve inline to no
    enrichment."""
    bindings = {s.id: _profile_binding(s) for s in sources}
    profile_sources = [s for s in sources if bindings[s.id] is not None]
    if not profile_sources:
        return {}

    schema_ids = {b.id for b in bindings.values() if b is not None and not b.is_saved_query}
    saved_query_ids = {b.id for b in bindings.values() if b is not None and b.is_saved_query}
    schemas_by_id: dict[str, Any] = {}
    if schema_ids:
        schema_model = apps.get_model("warehouse_sources", "ExternalDataSchema")
        schemas_by_id = {
            str(schema.id): schema
            for schema in schema_model.objects.filter(id__in=schema_ids, team_id=team_id).select_related(
                "source", "table"
            )
        }
    saved_queries_by_id: dict[str, Any] = {}
    if saved_query_ids:
        saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        saved_queries_by_id = {
            str(saved_query.id): saved_query
            for saved_query in saved_query_model.objects.filter(id__in=saved_query_ids, team_id=team_id).exclude(
                deleted=True
            )
        }

    # Latest run per source in one query: DISTINCT ON (source_id) keeps the newest row per source.
    latest_run_by_source_id: dict[Any, CustomPropertySyncRun] = {
        run.source_id: run
        for run in CustomPropertySyncRun.objects.for_team(team_id)
        .filter(source_id__in=[s.id for s in profile_sources])
        .order_by("source_id", "-created_at")
        .distinct("source_id")
    }
    enrichment: dict[Any, tuple[_ProfileWarehouseMeta | None, CustomPropertySyncRun | None]] = {}
    authorized_runs: list[CustomPropertySyncRun | None] = []
    for source in profile_sources:
        binding = bindings[source.id]
        assert binding is not None  # profile_sources is filtered on exactly this
        meta = _batched_meta(binding, schemas_by_id, saved_queries_by_id, user_access_control)
        latest = latest_run_by_source_id.get(source.id) if meta is not None else None
        # Only mutate runs the caller can view; expiring runs for hidden warehouse objects would let a
        # denied viewer flip their status through the source-list endpoint.
        if latest is not None:
            authorized_runs.append(latest)
        enrichment[source.id] = (meta, latest)
    _expire_stale_running_runs(team_id, authorized_runs)
    return enrichment


def _batched_meta(
    binding: "WarehouseBinding",
    schemas_by_id: dict[str, Any],
    saved_queries_by_id: dict[str, Any],
    user_access_control: "UserAccessControl | None",
) -> _ProfileWarehouseMeta | None:
    """One binding's metadata from the prefetched maps, or None when it is missing or access-denied.
    The access check mirrors the per-row resolvers: the import source for a schema, the view itself for
    a saved query."""
    if binding.is_saved_query:
        saved_query = saved_queries_by_id.get(binding.id)
        if saved_query is None:
            return None
        if user_access_control is not None and not user_access_control.check_access_level_for_object(
            saved_query, required_level="viewer"
        ):
            return None
        return _saved_query_meta(saved_query)

    schema = schemas_by_id.get(binding.id)
    if schema is None:
        return None
    if user_access_control is not None and not user_access_control.check_access_level_for_object(
        schema.source, required_level="viewer"
    ):
        return None
    return _schema_meta(schema)


def _saved_query_belongs_to_team(team_id: int, saved_query_id) -> bool:
    """Whether the saved query exists for this team and isn't soft-deleted. Uses ``apps.get_model`` so
    customer_analytics never imports data_modeling (which isn't a dependency)."""
    saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    return saved_query_model.objects.filter(id=saved_query_id, team_id=team_id).exclude(deleted=True).exists()


def _materialized_saved_query_belongs_to_team(team_id: int, saved_query_id) -> bool:
    """Whether the saved query resolves for this team *and* is materialized. A profile source reads the
    view's Delta table directly, which only a materialized view has."""
    saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    return (
        saved_query_model.objects.filter(id=saved_query_id, team_id=team_id, is_materialized=True)
        .exclude(deleted=True)
        .exists()
    )


def _external_data_schema_belongs_to_team(team_id: int, schema_id) -> bool:
    """Whether the warehouse schema (raw synced table) exists for this team. ``apps.get_model`` keeps
    customer_analytics from importing warehouse_sources internals (isolation)."""
    schema_model = apps.get_model("warehouse_sources", "ExternalDataSchema")
    return schema_model.objects.filter(id=schema_id, team_id=team_id).exists()


def _validate_column_property_map(column_property_map: Any) -> dict[str, str]:
    """A person-source's column->property map must be a non-empty {str: non-empty str} object."""
    if not isinstance(column_property_map, dict) or not column_property_map:
        raise CustomPropertySourceValidationError("column_property_map must be a non-empty object.")
    for column, property_name in column_property_map.items():
        if not isinstance(column, str) or not column:
            raise CustomPropertySourceValidationError("column_property_map keys must be non-empty column names.")
        if not isinstance(property_name, str) or not property_name:
            raise CustomPropertySourceValidationError("column_property_map values must be non-empty property names.")
    return column_property_map


def _validate_column_descriptions(column_descriptions: Any, mapped_columns: set[str]) -> dict[str, str]:
    """Optional {warehouse_column: description} for a person source. Descriptions are keyed by the
    same warehouse columns the source maps; unknown columns and blank descriptions are dropped."""
    if column_descriptions is None:
        return {}
    if not isinstance(column_descriptions, dict):
        raise CustomPropertySourceValidationError("column_descriptions must be an object.")
    cleaned: dict[str, str] = {}
    for column, description in column_descriptions.items():
        if column not in mapped_columns:
            continue
        if description is None or (isinstance(description, str) and not description.strip()):
            continue
        if not isinstance(description, str):
            raise CustomPropertySourceValidationError("column_descriptions values must be strings.")
        cleaned[column] = description.strip()
    return cleaned


def _enqueue_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    """Dispatch the sync task by name. Enqueue failure must not fail the originating write, so it's swallowed."""
    try:
        current_app.send_task(
            "customer_analytics.process_custom_property_sync",
            kwargs={"team_id": team_id, "saved_query_id": saved_query_id},
        )
    except Exception as e:
        capture_exception(e)


def _enqueue_sync_if_enabled(source: CustomPropertySource) -> None:
    """Run an initial sync after the source is saved so its values populate immediately rather than
    waiting for the next materialization. Skips disabled sources and ones whose view was deleted."""
    if not source.is_enabled or source.saved_query_id is None:
        return
    team_id, saved_query_id = source.team_id, str(source.saved_query_id)
    transaction.on_commit(lambda: _enqueue_custom_property_sync(team_id, saved_query_id))


# Targets fed by the warehouse staging/sync pipeline (person + group), as opposed to the account
# materialized-view path. These share the sync-now / backfill / run-history machinery.
_WAREHOUSE_PROFILE_TARGETS = (TargetType.PERSON.value, TargetType.GROUP.value)

_ONE_PROFILE_BINDING_ERROR = "A person/group property source needs exactly one of external_data_schema and saved_query."


# A run row only reaches a terminal state when its activity records one. Account segment workflows can
# retry for a full day, while profile sync activities time out after six hours.
STALE_RUNNING_RUN_AFTER = timedelta(hours=6)
STALE_ACCOUNT_RUNNING_RUN_AFTER = timedelta(hours=25)
STALE_RUNNING_RUN_ERROR = (
    "This run stopped reporting progress. Run the warehouse source again. If it keeps failing, contact support."
)


def _expire_stale_running_runs(team_id: int, runs: "Iterable[CustomPropertySyncRun | None]") -> None:
    """Fail abandoned 'running' rows, both in the database and in the passed-in objects so the caller
    serializes what it just wrote. Runs on the read paths the UI polls, so a stuck row self-heals."""
    now = timezone.now()
    stale = [
        run
        for run in runs
        if run is not None
        and run.status == SyncStatus.RUNNING.value
        and (run.started_at or run.created_at)
        < now - (STALE_ACCOUNT_RUNNING_RUN_AFTER if run.segment is not None else STALE_RUNNING_RUN_AFTER)
    ]
    if not stale:
        return
    finished_at = timezone.now()
    CustomPropertySyncRun.objects.for_team(team_id).filter(id__in=[run.id for run in stale]).update(
        status=SyncStatus.FAILED.value, finished_at=finished_at, error=STALE_RUNNING_RUN_ERROR
    )
    for run in stale:
        run.status = SyncStatus.FAILED.value
        run.finished_at = finished_at
        run.error = STALE_RUNNING_RUN_ERROR


def _create_running_runs(team_id: int, binding: "WarehouseBinding", trigger: str) -> list[Any]:
    """Insert a 'running' run for each enabled person/group source on the binding that isn't already
    running. The UI shows these as in-progress and disables the trigger while they exist; the sync and
    backfill activities reconcile them to their terminal state (see record_sync_run). Skipping sources
    that already have a running run makes this a no-op when a run for the table is already in flight
    (coalesced). Returns the source ids a placeholder was created for, so the caller can reconcile them
    to FAILED if the workflow start never happens (see ``_fail_created_runs``)."""
    # A source and a run name the same binding through different columns: a source's schema binding is
    # the `external_data_schema` FK, a run's is the plain `schema_id`.
    source_field = "saved_query_id" if binding.is_saved_query else "external_data_schema_id"
    run_field = "saved_query_id" if binding.is_saved_query else "schema_id"
    with transaction.atomic():
        # Lock the candidate sources so a concurrent trigger for the same binding can't pass the
        # "already running" check and insert a duplicate RUNNING row before this one commits.
        sources = list(
            CustomPropertySource.objects.for_team(team_id)
            .filter(
                is_enabled=True,
                definition__target_type__in=_WAREHOUSE_PROFILE_TARGETS,
                **{source_field: binding.id},
            )
            .select_for_update()
        )
        if not sources:
            return []
        running = list(
            CustomPropertySyncRun.objects.for_team(team_id).filter(source__in=sources, status=SyncStatus.RUNNING.value)
        )
        # An abandoned row must not coalesce away a fresh trigger.
        _expire_stale_running_runs(team_id, running)
        already_running = {run.source_id for run in running if run.status == SyncStatus.RUNNING.value}
        to_create = [source for source in sources if source.id not in already_running]
        now = timezone.now()
        CustomPropertySyncRun.objects.bulk_create(
            [
                CustomPropertySyncRun(
                    team_id=team_id,
                    source=source,
                    trigger=trigger,
                    status=SyncStatus.RUNNING.value,
                    started_at=now,
                    **{run_field: binding.id},
                )
                for source in to_create
            ]
        )
    return [source.id for source in to_create]


def _fail_created_runs(team_id: int, source_ids: list[Any], error: str) -> None:
    """Reconcile the RUNNING placeholders just created for these sources to FAILED. Called when the
    workflow start never happened (Temporal unreachable), so the rows don't sit 'running' forever with
    the UI trigger disabled, and the next attempt isn't coalesced against a dead placeholder."""
    if not source_ids:
        return
    CustomPropertySyncRun.objects.for_team(team_id).filter(
        source_id__in=source_ids, status=SyncStatus.RUNNING.value
    ).update(status=SyncStatus.FAILED.value, finished_at=timezone.now(), error=error)


def _start_backfill(team_id: int, binding: "WarehouseBinding", trigger: str) -> None:
    """Start the person-property backfill workflow. Failure must not fail the originating write."""
    created_source_ids: list[Any] = []
    # The temporal client is heavy; keep it off the CA facade import (django.setup) path. Imported
    # before the try so the except clause below can name WarehouseBindingMissingError even when an
    # earlier line raises.
    from products.warehouse_sources.backend.facade.temporal import (  # noqa: PLC0415
        WarehouseBindingMissingError,
        start_person_property_backfill,
    )

    try:
        # Placeholder rows before starting, so the activity always finds a running row to reconcile.
        created_source_ids = _create_running_runs(team_id, binding, trigger)
        start_person_property_backfill(team_id=team_id, binding=binding, trigger=trigger)
    except WarehouseBindingMissingError:
        # The warehouse object was deleted between saving the source and this deferred start. There is
        # nothing to back-fill, so reconcile the placeholders without capturing it as an error.
        _fail_created_runs(team_id, created_source_ids, "The warehouse table or view for this source no longer exists.")
    except Exception as e:
        # The workflow never started, so nothing will reconcile the placeholders — fail them here.
        _fail_created_runs(team_id, created_source_ids, "Failed to start backfill")
        capture_exception(e)


def _start_person_backfill_if_enabled(source: CustomPropertySource) -> None:
    """Auto-start a backfill after a person/group source is created/enabled so historical rows populate
    immediately rather than waiting for the next warehouse run. Profile sources only (an account source
    has its own Celery sync); deduped per table by the workflow id."""
    binding = _profile_binding(source)
    if not source.is_enabled or binding is None:
        return
    team_id = source.team_id
    transaction.on_commit(lambda: _start_backfill(team_id, binding, "backfill"))


def _triggerable_profile_binding(team_id: int, source_id: str) -> "WarehouseBinding | None":
    """The warehouse object to act on for a person/group-property trigger, or None when the source isn't
    a valid, flag-enabled warehouse-profile source (→ the view returns 400)."""
    source = CustomPropertySource.objects.for_team(team_id).filter(id=source_id).select_related("definition").first()
    if source is None:
        return None
    # A disabled source (e.g. auto-disabled after repeated failures) can't be re-triggered until it's
    # re-enabled — otherwise the "sync now"/backfill actions would keep launching billable warehouse
    # runs for a mapping the system already turned off.
    if not source.is_enabled:
        return None
    if not person_properties_flag_enabled(team_id):
        return None
    return _profile_binding(source)


def _assert_warehouse_access(
    team_id: int,
    binding: "WarehouseBinding | None",
    user_access_control: "UserAccessControl | None",
    level: str,
) -> None:
    """A profile source drives a real warehouse run, so acting on it or reading its warehouse metadata
    requires the caller's object-level access to what it reads at ``level``, not account-scope access
    alone: the ``external_data_source`` for a schema, the ``warehouse_view`` for a materialized view.
    Mirrors the canonical warehouse endpoints, which gate through ``get_object``. ``None`` (service auth,
    which the permission layer skips object checks for) is a no-op, matching ``_enforce_object_access``.
    Raises ``ResourceForbiddenError`` (→ 403) when the caller is denied. A warehouse object that no
    longer resolves is a no-op: there is nothing left to protect, and the caller's own write will fail
    its validation. ``apps.get_model`` keeps this off a warehouse_sources/data_modeling internal import."""
    if user_access_control is None or binding is None:
        return
    if binding.is_saved_query:
        saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        saved_query = saved_query_model.objects.filter(id=binding.id, team_id=team_id).exclude(deleted=True).first()
        if saved_query is None:
            return
        _enforce_object_access(saved_query, user_access_control, level)
        return
    schema_model = apps.get_model("warehouse_sources", "ExternalDataSchema")
    schema = schema_model.objects.filter(id=binding.id, team_id=team_id).select_related("source").first()
    if schema is None:
        return
    _enforce_object_access(schema.source, user_access_control, level)


def _assert_warehouse_editor(
    team_id: int, binding: "WarehouseBinding | None", user_access_control: "UserAccessControl | None"
) -> None:
    """Editor gate for acting on a profile source — a manual sync/backfill, or creating/enabling the
    mapping (which auto-triggers one)."""
    _assert_warehouse_access(team_id, binding, user_access_control, "editor")


def _assert_warehouse_viewer(
    team_id: int, binding: "WarehouseBinding | None", user_access_control: "UserAccessControl | None"
) -> None:
    """Viewer gate for reading a profile source's warehouse run metadata (row counts, schedule, sync
    errors), which exposes the warehouse object it reads."""
    _assert_warehouse_access(team_id, binding, user_access_control, "viewer")


def trigger_person_property_sync(
    *, team_id: int, source_id: str, user_access_control: "UserAccessControl | None" = None
) -> bool:
    """ "Sync now" for a profile source: start a fresh warehouse run of whatever it reads — an import for
    a schema (billable), a materialization for a view. The person-property child runs off that run.
    Returns False for an invalid source (→ 400). Requires editor access to the warehouse object (→ 403),
    honors the team's warehouse sync pause (→ ``WarehouseSyncPausedError``), and rejects a view still on
    the older data-modeling schedule (→ ``ViewNotSyncableError``)."""
    binding = _triggerable_profile_binding(team_id, source_id)
    if binding is None:
        return False
    _assert_warehouse_editor(team_id, binding, user_access_control)
    from products.warehouse_sources.backend.facade.temporal import (  # noqa: PLC0415
        ExternalDataSchemaSyncPausedError,
        SavedQueryNotFoundError,
        SavedQueryNotOnV2ScheduleError,
        trigger_saved_query_materialization,
        trigger_schema_sync,
    )

    # Open the run rows before the warehouse run starts, so the history shows it in progress right away
    # and the trigger buttons stay disabled until it settles. The person-property activity reconciles
    # them when the run reaches it (see record_sync_run).
    created_source_ids = _create_running_runs(team_id, binding, SyncTrigger.SYNC.value)
    try:
        if binding.is_saved_query:
            trigger_saved_query_materialization(team_id=team_id, saved_query_id=binding.id)
        else:
            trigger_schema_sync(team_id=team_id, schema_id=binding.id)
    except ExternalDataSchemaSyncPausedError as e:
        _fail_created_runs(team_id, created_source_ids, "Warehouse syncs are paused for this project")
        raise WarehouseSyncPausedError(str(e)) from e
    except (SavedQueryNotOnV2ScheduleError, SavedQueryNotFoundError) as e:
        _fail_created_runs(team_id, created_source_ids, str(e))
        raise ViewNotSyncableError(str(e)) from e
    except Exception:
        _fail_created_runs(team_id, created_source_ids, "Failed to start sync")
        raise
    return True


def trigger_person_property_backfill(
    *, team_id: int, source_id: str, trigger: str = "manual", user_access_control: "UserAccessControl | None" = None
) -> bool | None:
    """Start a backfill for a profile source's table. Returns True (started), False (already running →
    coalesced), or None for an invalid source (→ 400). Requires editor access to the warehouse object
    (→ 403)."""
    binding = _triggerable_profile_binding(team_id, source_id)
    if binding is None:
        return None
    _assert_warehouse_editor(team_id, binding, user_access_control)
    # Placeholder rows before starting, so the activity always finds a running row to reconcile.
    created_source_ids = _create_running_runs(team_id, binding, trigger)
    from products.warehouse_sources.backend.facade.temporal import (  # noqa: PLC0415
        WarehouseBindingMissingError,
        start_person_property_backfill,
    )

    try:
        return start_person_property_backfill(team_id=team_id, binding=binding, trigger=trigger)
    except WarehouseBindingMissingError:
        # The warehouse table or view was deleted after the placeholders were created; reconcile them
        # so the source isn't stuck 'running', and report an invalid source (→ 400) rather than a
        # coalesced run for a table that is gone.
        _fail_created_runs(team_id, created_source_ids, "The warehouse table or view for this source no longer exists.")
        return None
    except Exception:
        # The workflow never started; reconcile the placeholders so the source isn't stuck 'running'
        # with its trigger disabled, then surface the error to the caller.
        _fail_created_runs(team_id, created_source_ids, "Failed to start backfill")
        raise


def list_custom_property_sources(
    team_id: int,
    offset: int,
    limit: int,
    user_access_control: "UserAccessControl | None" = None,
    *,
    exclude_group_targets: bool = False,
) -> tuple[list[contracts.CustomPropertySourceView], int]:
    """Custom-property sources for the team, newest first. Returns ``(page, total_count)``. Warehouse
    schedule/run enrichment per source is gated on the caller's warehouse-source viewer access.

    ``exclude_group_targets`` hides sources feeding a group-target definition from callers without
    ``group`` read authorization."""
    queryset = CustomPropertySource.objects.for_team(team_id).select_related("definition").order_by("-created_at")
    if exclude_group_targets:
        queryset = queryset.exclude(definition__target_type=TargetType.GROUP.value)
    total_count = queryset.count()
    page = list(queryset[offset : offset + limit])
    enrichment = _batch_source_enrichment(team_id, page, user_access_control)
    return [
        _to_custom_property_source_view(s, user_access_control, enrichment.get(s.id, _RESOLVE_ENRICHMENT_INLINE))
        for s in page
    ], total_count


def get_custom_property_source(
    team_id: int, source_id: str, user_access_control: "UserAccessControl | None" = None
) -> contracts.CustomPropertySourceView | None:
    source = CustomPropertySource.objects.for_team(team_id).select_related("definition").filter(id=source_id).first()
    return _to_custom_property_source_view(source, user_access_control) if source is not None else None


def get_custom_property_source_binding_id(team_id: int, source_id: str) -> str | None:
    """The id of the warehouse object a source reads — its saved query for a view binding, its external
    data schema for a table binding — or None when the source doesn't resolve or reads neither. Kept to
    two id columns (no definition join, no view building) because the sync throttle calls it per request
    to key its limit on the warehouse object rather than the mapping."""
    try:
        row = (
            CustomPropertySource.objects.for_team(team_id)
            .filter(id=source_id)
            .values_list("saved_query_id", "external_data_schema_id")
            .first()
        )
    except (ValidationError, ValueError):  # a non-UUID id from the URL is simply unknown
        return None
    if row is None:
        return None
    saved_query_id, schema_id = row
    binding_id = saved_query_id or schema_id
    return str(binding_id) if binding_id is not None else None


def create_custom_property_source(
    *,
    team_id: int,
    definition_id: str | UUID,
    key_column: str,
    is_enabled: bool,
    user: "User",
    saved_query_id: str | UUID | None = None,
    source_column: str | None = None,
    external_data_schema_id: str | UUID | None = None,
    column_property_map: dict | None = None,
    column_descriptions: dict | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> contracts.CustomPropertySourceView:
    definition = _get_team_scoped(CustomPropertyDefinition, team_id, definition_id)
    if definition is None:
        raise CustomPropertySourceValidationError("Custom property definition not found for this team.")

    # The definition's target decides which binding is valid: an account source reads one saved-query
    # column; a person/group source maps columns from either an imported schema's table or a
    # materialized view onto profile properties.
    create_kwargs: dict[str, Any] = {
        "team_id": team_id,
        "created_by": user,
        "definition_id": definition_id,
        "key_column": key_column,
        "is_enabled": is_enabled,
    }
    if definition.target_type in _WAREHOUSE_PROFILE_TARGETS:
        if saved_query_id is not None and external_data_schema_id is not None:
            raise CustomPropertySourceValidationError(_ONE_PROFILE_BINDING_ERROR)
        if source_column:
            raise CustomPropertySourceValidationError(
                "A person/group property source maps columns with column_property_map, not source_column."
            )
        # Validate the map shape in memory before the DB lookups below.
        validated_map = _validate_column_property_map(column_property_map)
        create_kwargs["column_property_map"] = validated_map
        create_kwargs["column_descriptions"] = _validate_column_descriptions(
            column_descriptions, set(validated_map.keys())
        )
        if saved_query_id is not None:
            # An unmaterialized view has no table to read, so the source could never sync — reject it
            # here rather than creating a mapping that stays silently empty.
            if not _materialized_saved_query_belongs_to_team(team_id, saved_query_id):
                raise CustomPropertySourceValidationError("Materialized view not found for this team.")
            binding = saved_query_binding(saved_query_id)
            create_kwargs["saved_query_id"] = saved_query_id
        elif external_data_schema_id is not None:
            if not _external_data_schema_belongs_to_team(team_id, external_data_schema_id):
                raise CustomPropertySourceValidationError("Warehouse schema not found for this team.")
            binding = schema_binding(external_data_schema_id)
            create_kwargs["external_data_schema_id"] = external_data_schema_id
        else:
            raise CustomPropertySourceValidationError(_ONE_PROFILE_BINDING_ERROR)
        # Mapping (and enabling) a warehouse table into profile properties drives real warehouse runs,
        # so require the caller's editor access on what it reads, not account-scope editor alone.
        _assert_warehouse_editor(team_id, binding, user_access_control)
    else:
        if saved_query_id is None or not source_column:
            raise CustomPropertySourceValidationError(
                "An account property source needs a saved_query and source_column."
            )
        if external_data_schema_id is not None or column_property_map is not None:
            raise CustomPropertySourceValidationError(
                "An account property source uses saved_query + source_column, not external_data_schema."
            )
        if not _saved_query_belongs_to_team(team_id, saved_query_id):
            raise CustomPropertySourceValidationError("Saved query not found for this team.")
        create_kwargs["saved_query_id"] = saved_query_id
        create_kwargs["source_column"] = source_column

    try:
        source = CustomPropertySource.objects.for_team(team_id).create(**create_kwargs)
    except IntegrityError as exc:
        # Both FKs are team-validated above, so the only expected violation is the definition's
        # one-to-one uniqueness; re-raise anything else instead of mislabeling it as a duplicate.
        if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
        raise CustomPropertySourceValidationError("This custom property already has a source.")
    _enqueue_sync_if_enabled(source)
    _start_person_backfill_if_enabled(source)
    return _to_custom_property_source_view(source, user_access_control)


def update_custom_property_source(
    *, team_id: int, source_id: str, fields: dict[str, Any], user_access_control: "UserAccessControl | None" = None
) -> contracts.CustomPropertySourceView | None:
    """Apply ``fields`` (source_column / key_column / is_enabled) to a team-scoped source. Re-enabling
    (is_enabled False→True) resets the failure streak and clears the last error. Returns None (→ 404)
    when no source matches."""
    source = CustomPropertySource.objects.for_team(team_id).select_related("definition").filter(id=source_id).first()
    if source is None:
        return None
    reenabling = fields.get("is_enabled") is True and not source.is_enabled
    columns_changed = any(
        attr in fields and fields[attr] != getattr(source, attr) for attr in ("source_column", "key_column")
    )
    # A profile source's backfill drives a real warehouse run, so any change that will trigger one —
    # re-enabling, or changing the mapped columns while it stays enabled — requires the caller's editor
    # access on the warehouse object, not account-scope editor alone (matching create). Both routes reach
    # _start_person_backfill_if_enabled below via ``reenabling or columns_changed``; ``is_enabled`` here is
    # the post-update state that decides whether that helper actually starts a backfill.
    will_be_enabled = fields.get("is_enabled", source.is_enabled) is True
    binding = _profile_binding(source)
    if binding is not None and will_be_enabled and (reenabling or columns_changed):
        _assert_warehouse_editor(team_id, binding, user_access_control)
    for attr, value in fields.items():
        setattr(source, attr, value)
    if reenabling:
        source.consecutive_failures = 0
        source.last_sync_error = None
    source.save()
    # Only re-sync on a change that affects what gets written — not on every (possibly no-op) PATCH.
    if reenabling or columns_changed:
        _enqueue_sync_if_enabled(source)
        _start_person_backfill_if_enabled(source)
    return _to_custom_property_source_view(source, user_access_control)


def delete_custom_property_source(
    *, team_id: int, source_id: str, user_access_control: "UserAccessControl | None" = None
) -> bool:
    """Delete a team-scoped source. Returns False when none matched (→ 404). Deleting a profile source
    permanently stops its warehouse-driven updates, so it requires the caller's editor access on the
    warehouse object (→ 403 via ``ResourceForbiddenError``), matching create/update/sync/backfill."""
    source = CustomPropertySource.objects.for_team(team_id).select_related("definition").filter(id=source_id).first()
    if source is None:
        return False
    _assert_warehouse_editor(team_id, _profile_binding(source), user_access_control)
    deleted, _ = source.delete()
    return deleted > 0


def list_custom_property_sync_runs(
    team_id: int,
    source_id: str,
    offset: int,
    limit: int,
    user_access_control: "UserAccessControl | None" = None,
    include_temporal_urls: bool = False,
    search: str | None = None,
) -> tuple[list[contracts.CustomPropertySyncRunView], int]:
    """Warehouse-backed custom property sync runs for a source, newest first. Returns ``(page, total_count)``.
    Scoped by team and source, so another team's or source's runs are never returned. Profile-source
    histories require viewer access to their warehouse object; account-source histories are visible to
    the same callers who can view the source."""
    source = CustomPropertySource.objects.for_team(team_id).select_related("definition").filter(id=source_id).first()
    if source is not None:
        _assert_warehouse_viewer(team_id, _profile_binding(source), user_access_control)
    queryset: QuerySet[CustomPropertySyncRun] = CustomPropertySyncRun.objects.for_team(team_id).filter(
        source_id=source_id
    )
    if search:
        queryset = cast(
            "QuerySet[CustomPropertySyncRun]",
            queryset.annotate(workflow_run_id_text=Cast("workflow_run_id", output_field=CharField())).filter(
                Q(job_id__icontains=search)
                | Q(workflow_id__icontains=search)
                | Q(workflow_run_id_text__icontains=search)
                | Q(status__icontains=search)
                | Q(segment__icontains=search)
                | Q(trigger__icontains=search)
                | Q(error__icontains=search)
            ),
        )
    queryset = queryset.order_by("-created_at")
    total_count = queryset.count()
    page = list(queryset[offset : offset + limit])
    _expire_stale_running_runs(team_id, page)
    return [_to_sync_run_view(run, include_temporal_url=include_temporal_urls) for run in page], total_count


FeatureRequestValidationError = _feature_requests_logic.FeatureRequestValidationError
FeatureRequestProductAreaConflictError = _feature_requests_logic.FeatureRequestProductAreaConflictError
FeatureRequestConflictError = _feature_requests_logic.FeatureRequestConflictError


def list_feature_request_product_areas(
    team_id: int, *, include_inactive: bool = False
) -> list[contracts.FeatureRequestProductAreaView]:
    return _feature_requests_logic.list_product_areas(team_id, include_inactive=include_inactive)


def create_feature_request_product_area(
    *, team_id: int, name: str, display_order: int, actor_id: int
) -> contracts.FeatureRequestProductAreaView:
    return _feature_requests_logic.create_product_area(
        team_id=team_id,
        name=name,
        display_order=display_order,
        actor_id=actor_id,
    )


def update_feature_request_product_area(
    *,
    team_id: int,
    product_area_id: UUID,
    name: str | None,
    display_order: int | None,
    is_active: bool | None,
    actor_id: int,
) -> contracts.FeatureRequestProductAreaView | None:
    return _feature_requests_logic.update_product_area(
        team_id=team_id,
        product_area_id=product_area_id,
        name=name,
        display_order=display_order,
        is_active=is_active,
        actor_id=actor_id,
    )


def list_feature_requests(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    filters: contracts.FeatureRequestListFilters,
    offset: int,
    limit: int,
) -> tuple[list[contracts.FeatureRequestView], int]:
    return _feature_requests_logic.list_feature_requests(
        team_id=team_id,
        user_access_control=user_access_control,
        filters=filters,
        offset=offset,
        limit=limit,
    )


def get_feature_request(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.get_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def create_feature_request(
    *,
    team_id: int,
    input: contracts.CreateFeatureRequestInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestCreateOutcome:
    return _feature_requests_logic.create_feature_request(
        team_id=team_id,
        input=input,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def update_feature_request(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.UpdateFeatureRequestInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.update_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        input=input,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def add_feature_request_account(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.AddFeatureRequestAccountInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.add_feature_request_account(
        team_id=team_id,
        feature_request_id=feature_request_id,
        input=input,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def create_feature_request_evidence(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.CreateFeatureRequestEvidenceInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.create_feature_request_evidence(
        team_id=team_id,
        feature_request_id=feature_request_id,
        input=input,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def update_feature_request_evidence(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.UpdateFeatureRequestEvidenceInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.update_feature_request_evidence(
        team_id=team_id,
        feature_request_id=feature_request_id,
        input=input,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def delete_feature_request_evidence(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.DeleteFeatureRequestEvidenceInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.delete_feature_request_evidence(
        team_id=team_id,
        feature_request_id=feature_request_id,
        input=input,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def set_feature_request_archived(
    *,
    team_id: int,
    feature_request_id: UUID,
    expected_version: int,
    archived: bool,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    return _feature_requests_logic.set_feature_request_archived(
        team_id=team_id,
        feature_request_id=feature_request_id,
        expected_version=expected_version,
        archived=archived,
        actor_id=actor_id,
        user_access_control=user_access_control,
    )


def list_feature_request_history(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> list[contracts.FeatureRequestHistoryView] | None:
    return _feature_requests_logic.list_feature_request_history(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def list_feature_request_status_history(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> list[contracts.FeatureRequestStatusHistoryView] | None:
    return _feature_requests_logic.list_feature_request_status_history(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


# --- CustomerJourney ---


def _to_customer_journey_view(journey: CustomerJourney) -> contracts.CustomerJourneyView:
    return contracts.CustomerJourneyView(
        id=journey.id,
        insight=journey.insight_id,
        name=journey.name,
        description=journey.description,
        created_at=journey.created_at,
        created_by=journey.created_by_id,
        updated_at=journey.updated_at,
    )


def _customer_journeys_queryset(team_id: int):
    """Team-scoped customer journeys, ordered by creation. Object-level access filtering is
    applied by the caller (list applies it; detail relies on the per-object check)."""
    return CustomerJourney.objects.order_by("created_at").filter(team_id=team_id)


def insight_belongs_to_team(team_id: int, insight_id: int) -> bool:
    """Whether the given insight is in the team — backs the journey serializer's
    ``validate_insight`` (kept as a cheap existence probe so the model stays hidden)."""
    from products.product_analytics.backend.facade.models import Insight

    return Insight.objects.filter(pk=insight_id, team_id=team_id).exists()


def list_customer_journeys(
    team_id: int, offset: int, limit: int, user_access_control: "UserAccessControl"
) -> tuple[list[contracts.CustomerJourneyView], int]:
    queryset = user_access_control.filter_queryset_by_access_level(_customer_journeys_queryset(team_id))
    total_count = queryset.count()
    page = queryset[offset : offset + limit]
    return [_to_customer_journey_view(j) for j in page], total_count


def get_customer_journey(
    team_id: int, journey_id: str, user_access_control: "UserAccessControl", required_level: str | None
) -> contracts.CustomerJourneyView:
    """Fetch one team-scoped journey, enforcing object-level access. Raises
    ``CustomerJourney.DoesNotExist`` (→ 404) when absent and ``ResourceForbiddenError``
    (→ 403) when the caller lacks object access — mirroring the old viewset."""
    journey = _get_object_or_raise(_customer_journeys_queryset(team_id), journey_id, CustomerJourney)
    _enforce_object_access(journey, user_access_control, required_level)
    return _to_customer_journey_view(journey)


def create_customer_journey(
    *,
    team_id: int,
    insight_id: int,
    name: str,
    description: str | None,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.CustomerJourneyView:
    try:
        journey = CustomerJourney.objects.create(
            team_id=team_id, created_by=user, insight_id=insight_id, name=name, description=description
        )
    except IntegrityError:
        raise CustomerJourneyConflictError("A customer journey already exists for this insight.")
    _log_activity_swallowing(
        instance=journey,
        scope="CustomerJourney",
        activity="created",
        name=journey.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    return _to_customer_journey_view(journey)


def update_customer_journey(
    *,
    team_id: int,
    journey_id: str,
    fields: dict[str, Any],
    user_access_control: "UserAccessControl",
    required_level: str | None,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.CustomerJourneyView:
    journey = _get_object_or_raise(_customer_journeys_queryset(team_id), journey_id, CustomerJourney)
    _enforce_object_access(journey, user_access_control, required_level)
    previous = CustomerJourney.objects.get(pk=journey.pk)
    for attr, value in fields.items():
        setattr(journey, attr, value)
    journey.save()
    _log_activity_swallowing(
        instance=journey,
        scope="CustomerJourney",
        activity="updated",
        name=journey.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        previous=previous,
    )
    return _to_customer_journey_view(journey)


def delete_customer_journey(
    *,
    team_id: int,
    journey_id: str,
    user_access_control: "UserAccessControl",
    required_level: str | None,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> None:
    journey = _get_object_or_raise(_customer_journeys_queryset(team_id), journey_id, CustomerJourney)
    _enforce_object_access(journey, user_access_control, required_level)
    _log_activity_swallowing(
        instance=journey,
        scope="CustomerJourney",
        activity="deleted",
        name=journey.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    journey.delete()


# --- Account (full CRUD view) ---


def _account_view_tags(account: Account) -> list[str]:
    """Tags for an account, preferring the prefetched list when present (list path) so
    the query budget stays flat — matching the old ``TaggedItemSerializerMixin``."""
    if hasattr(account, "prefetched_tags"):
        return [p.tag.name for p in account.prefetched_tags]
    return list(account.tagged_items.values_list("tag__name", flat=True)) if account.pk else []


def _account_view_notebooks(account: Account) -> list[str]:
    return [link.notebook.short_id for link in account.notebooks.all()]


def _to_account_view(account: Account) -> contracts.AccountView:
    return contracts.AccountView(
        id=account.id,
        name=account.name,
        external_id=account.external_id,
        # Raw stored JSON (already ``exclude_unset`` from the manager), so an account with
        # no assignments serializes ``properties`` as ``{}`` exactly as before. Retired role
        # keys are dropped: rows not yet backfilled must not leak them into responses, or the
        # frontend's read-modify-write of ``properties`` sends them back and gets a 400.
        properties={k: v for k, v in (account._properties or {}).items() if k not in RETIRED_ROLE_KEYS},
        # Unsorted, matching the old ``TaggedItemSerializerMixin.to_representation`` output.
        tags=_account_view_tags(account),
        notebooks=_account_view_notebooks(account),
        slack_summary_cadence=account.slack_summary_cadence,
        churned_at=account.churned_at,
        ignored_at=account.ignored_at,
        created_at=account.created_at,
        created_by=account.created_by_id,
        updated_at=account.updated_at,
    )


class InvalidAccountTableColumn(ValueError):
    pass


ACCOUNT_TABLE_MAX_HISTORY_POINTS = 50_000


def _account_table_field_values(
    account: Account, fields: frozenset[contracts.AccountTableField]
) -> dict[contracts.AccountTableField, str | None]:
    properties = account.properties
    values: dict[contracts.AccountTableField, str | None] = {}
    for field in sorted(fields, key=lambda account_field: account_field.value):
        match field:
            case contracts.AccountTableField.NAME:
                values[field] = account.name
            case contracts.AccountTableField.EXTERNAL_ID:
                values[field] = account.external_id
            case contracts.AccountTableField.CREATED_AT:
                values[field] = account.created_at.isoformat() if account.created_at else None
            case contracts.AccountTableField.UPDATED_AT:
                values[field] = account.updated_at.isoformat() if account.updated_at else None
            case contracts.AccountTableField.CHURNED_AT:
                values[field] = account.churned_at.isoformat() if account.churned_at else None
            case contracts.AccountTableField.IGNORED_AT:
                values[field] = account.ignored_at.isoformat() if account.ignored_at else None
            case contracts.AccountTableField.STRIPE_CUSTOMER_ID:
                values[field] = properties.stripe_customer_id
            case contracts.AccountTableField.HUBSPOT_DEAL_ID:
                values[field] = properties.hubspot_deal_id
            case contracts.AccountTableField.BILLING_ID:
                values[field] = properties.billing_id
            case contracts.AccountTableField.SFDC_ID:
                values[field] = properties.sfdc_id
            case contracts.AccountTableField.ZENDESK_ID:
                values[field] = properties.zendesk_id
            case _:
                raise ValueError(f"Unsupported account table field: {field}")
    return values


def _validate_account_table_definitions(
    *,
    team_id: int,
    selection: contracts.AccountTableColumnSelection,
    filters: tuple[contracts.AccountTableFilter, ...],
    sort: contracts.AccountTableSort | None,
) -> dict[UUID, DisplayType]:
    relationship_ids = set(selection.relationship_definition_ids)
    if sort and sort.kind == contracts.AccountTableSortKind.RELATIONSHIP:
        if sort.definition_id is None:
            raise InvalidAccountTableColumn("Relationship sorting requires a definition.")
        relationship_ids.add(sort.definition_id)
    if relationship_ids:
        valid_relationship_ids = set(
            AccountRelationshipDefinition.objects.for_team(team_id)
            .filter(id__in=relationship_ids)
            .values_list("id", flat=True)
        )
        invalid_relationship_ids = relationship_ids - valid_relationship_ids
        if invalid_relationship_ids:
            invalid_ids = ", ".join(sorted(str(definition_id) for definition_id in invalid_relationship_ids))
            raise InvalidAccountTableColumn(f"Unknown relationship definitions: {invalid_ids}")

    custom_property_ids = set(selection.custom_property_definition_ids) | set(selection.custom_property_history_windows)
    custom_property_ids.update(
        filter_.definition_id for filter_ in filters if isinstance(filter_, contracts.AccountTableCustomPropertyFilter)
    )
    if sort and sort.kind == contracts.AccountTableSortKind.CUSTOM_PROPERTY:
        if sort.definition_id is None:
            raise InvalidAccountTableColumn("Custom property sorting requires a definition.")
        custom_property_ids.add(sort.definition_id)
    if not custom_property_ids:
        return {}

    custom_property_display_types = {
        definition_id: DisplayType(display_type)
        for definition_id, display_type in CustomPropertyDefinition.objects.for_team(team_id)
        .filter(id__in=custom_property_ids, target_type=TargetType.ACCOUNT)
        .values_list("id", "display_type")
    }
    invalid_custom_property_ids = custom_property_ids - set(custom_property_display_types)
    if invalid_custom_property_ids:
        invalid_ids = ", ".join(sorted(str(definition_id) for definition_id in invalid_custom_property_ids))
        raise InvalidAccountTableColumn(f"Unknown account custom property definitions: {invalid_ids}")

    non_numeric_history_ids = {
        definition_id
        for definition_id in selection.custom_property_history_windows
        if custom_property_display_types[definition_id].value not in NUMERIC_DISPLAY_TYPES
    }
    if non_numeric_history_ids:
        invalid_ids = ", ".join(sorted(str(definition_id) for definition_id in non_numeric_history_ids))
        raise InvalidAccountTableColumn(f"Custom property history requires numeric definitions: {invalid_ids}")
    return custom_property_display_types


def _filters_account_table_field(
    filters: tuple[contracts.AccountTableFilter, ...], field: contracts.AccountTableField
) -> bool:
    return any(isinstance(filter_, contracts.AccountTableFieldFilter) and filter_.field == field for filter_ in filters)


def _apply_account_table_filters(
    queryset: QuerySet[Account],
    *,
    team_id: int,
    filters: tuple[contracts.AccountTableFilter, ...],
    custom_property_display_types: dict[UUID, DisplayType],
) -> QuerySet[Account]:
    try:
        return apply_account_filters(
            queryset,
            team_id=team_id,
            filters=filters,
            custom_property_display_types=custom_property_display_types,
        )
    except InvalidAccountFilter as error:
        raise InvalidAccountTableColumn(str(error)) from error


def _custom_property_sort_output_field(display_type: DisplayType) -> Field:
    return {
        DataType.STRING: TextField(),
        DataType.NUMERIC: FloatField(),
        DataType.BOOLEAN: BooleanField(),
        DataType.DATETIME: DateTimeField(),
    }[DATA_TYPE_BY_DISPLAY_TYPE[display_type]]


def _apply_account_table_sort(
    queryset: QuerySet[Account],
    *,
    team_id: int,
    sort: contracts.AccountTableSort | None,
    custom_property_display_types: dict[UUID, DisplayType],
) -> QuerySet[Account]:
    if sort is None:
        return queryset.order_by("-created_at", "-id")

    if sort.kind == contracts.AccountTableSortKind.ACCOUNT_FIELD:
        if sort.account_field is None:
            raise InvalidAccountTableColumn("Account field sorting requires a field.")
        direct_fields = {
            contracts.AccountTableField.NAME: "name",
            contracts.AccountTableField.EXTERNAL_ID: "external_id",
            contracts.AccountTableField.CREATED_AT: "created_at",
            contracts.AccountTableField.UPDATED_AT: "updated_at",
            contracts.AccountTableField.CHURNED_AT: "churned_at",
            contracts.AccountTableField.IGNORED_AT: "ignored_at",
        }
        if direct_field := direct_fields.get(sort.account_field):
            queryset = queryset.annotate(_account_table_sort=F(direct_field))
        else:
            queryset = queryset.annotate(_account_table_sort=KeyTextTransform(sort.account_field.value, "_properties"))
    elif sort.kind == contracts.AccountTableSortKind.TAGS:
        tag_values = (
            TaggedItem.objects.filter(account_id=OuterRef("pk"), tag__team_id=team_id)
            .values("account_id")
            .annotate(value=ArrayAgg("tag__name", order_by="tag__name"))
            .values("value")
        )
        queryset = queryset.annotate(_account_table_sort=Subquery(tag_values, output_field=ArrayField(CharField())))
    elif sort.kind == contracts.AccountTableSortKind.NOTE_COUNT:
        note_counts = (
            ResourceNotebook.objects.filter(account_id=OuterRef("pk"))
            .values("account_id")
            .annotate(value=Count("id"))
            .values("value")
        )
        queryset = queryset.annotate(
            _account_table_sort=Coalesce(Subquery(note_counts, output_field=IntegerField()), Value(0))
        )
    elif sort.kind == contracts.AccountTableSortKind.RELATIONSHIP:
        if sort.definition_id is None:
            raise InvalidAccountTableColumn("Relationship sorting requires a definition.")
        relationship_values = (
            AccountRelationship.objects.for_team(team_id)
            .filter(
                account_id=OuterRef("pk"),
                definition_id=sort.definition_id,
                ended_at__isnull=True,
                user_id__isnull=False,
            )
            .values("account_id")
            .annotate(value=ArrayAgg("user_id", order_by="user_id"))
            .values("value")
        )
        queryset = queryset.annotate(
            _account_table_sort=Subquery(relationship_values, output_field=ArrayField(IntegerField()))
        )
    elif sort.kind == contracts.AccountTableSortKind.CUSTOM_PROPERTY:
        if sort.definition_id is None:
            raise InvalidAccountTableColumn("Custom property sorting requires a definition.")
        display_type = custom_property_display_types[sort.definition_id]
        value_field = {
            DataType.STRING: "value_str",
            DataType.NUMERIC: "value_num",
            DataType.BOOLEAN: "value_bool",
            DataType.DATETIME: "value_datetime",
        }[DATA_TYPE_BY_DISPLAY_TYPE[display_type]]
        custom_property_value = CustomPropertyValue.objects.for_team(team_id).filter(
            account_id=OuterRef("pk"), definition_id=sort.definition_id, is_deleted=False
        )
        queryset = queryset.annotate(
            _account_table_sort=Subquery(
                custom_property_value.values(value_field)[:1],
                output_field=_custom_property_sort_output_field(display_type),
            )
        )

    order = F("_account_table_sort")
    primary_order = (
        order.asc(nulls_last=True)
        if sort.direction == contracts.AccountTableSortDirection.ASCENDING
        else order.desc(nulls_last=True)
    )
    return queryset.order_by(primary_order, "id")


class _PercentileCont(Aggregate):
    function = "PERCENTILE_CONT"
    template = "%(function)s(0.5) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()


def query_accounts_metrics(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    filters: tuple[contracts.AccountTableFilter, ...],
    metrics: tuple[contracts.AccountTableMetric, ...],
    include_churned: bool = False,
    include_ignored: bool = False,
) -> list[float | int | None]:
    definition_ids = frozenset(
        metric.definition_id
        for metric in metrics
        if isinstance(metric, contracts.AccountTableAggregateMetric | contracts.AccountTableCountThresholdMetric)
    )
    custom_property_display_types = _validate_account_table_definitions(
        team_id=team_id,
        selection=contracts.AccountTableColumnSelection(custom_property_definition_ids=definition_ids),
        filters=filters,
        sort=None,
    )
    for definition_id in definition_ids:
        if DATA_TYPE_BY_DISPLAY_TYPE[custom_property_display_types[definition_id]] != DataType.NUMERIC:
            raise InvalidAccountTableColumn("Account table metrics require numeric custom properties.")

    accounts = _accounts_queryset(team_id, user_access_control)
    if not include_churned and not _filters_account_table_field(filters, contracts.AccountTableField.CHURNED_AT):
        accounts = accounts.filter(churned_at__isnull=True)
    if not include_ignored and not _filters_account_table_field(filters, contracts.AccountTableField.IGNORED_AT):
        accounts = accounts.filter(ignored_at__isnull=True)
    accounts = _apply_account_table_filters(
        accounts,
        team_id=team_id,
        filters=filters,
        custom_property_display_types=custom_property_display_types,
    )
    results: list[float | int | None] = [None] * len(metrics)
    for index, metric in enumerate(metrics):
        if isinstance(metric, contracts.AccountTableCountMetric):
            results[index] = accounts.count()

    aggregate_expressions: dict[str, Aggregate] = {}
    for index, metric in enumerate(metrics):
        alias = f"metric_{index}"
        if isinstance(metric, contracts.AccountTableAggregateMetric):
            aggregate_type = {
                contracts.AccountTableAggregation.SUM: Sum,
                contracts.AccountTableAggregation.AVERAGE: Avg,
                contracts.AccountTableAggregation.MINIMUM: Min,
                contracts.AccountTableAggregation.MAXIMUM: Max,
                contracts.AccountTableAggregation.MEDIAN: _PercentileCont,
            }[metric.aggregation]
            aggregate_expressions[alias] = aggregate_type(
                "value_num",
                filter=Q(definition_id=metric.definition_id),
            )
        elif isinstance(metric, contracts.AccountTableCountThresholdMetric):
            comparison = {
                contracts.AccountTableThresholdOperator.GREATER_THAN: Q(value_num__gt=metric.value),
                contracts.AccountTableThresholdOperator.GREATER_THAN_OR_EQUAL: Q(value_num__gte=metric.value),
                contracts.AccountTableThresholdOperator.LESS_THAN: Q(value_num__lt=metric.value),
                contracts.AccountTableThresholdOperator.LESS_THAN_OR_EQUAL: Q(value_num__lte=metric.value),
                contracts.AccountTableThresholdOperator.EQUAL: Q(value_num=metric.value),
                contracts.AccountTableThresholdOperator.NOT_EQUAL: ~Q(value_num=metric.value),
            }[metric.operator]
            aggregate_expressions[alias] = Count(
                "account_id",
                filter=Q(definition_id=metric.definition_id) & comparison,
            )

    if aggregate_expressions:
        values = CustomPropertyValue.objects.for_team(team_id).filter(
            account_id__in=accounts.order_by().values("id"),
            is_deleted=False,
            value_num__isnull=False,
        )
        aggregated = values.aggregate(**aggregate_expressions)
        for index, metric in enumerate(metrics):
            value = aggregated.get(f"metric_{index}")
            if isinstance(metric, contracts.AccountTableAggregateMetric) and value is not None:
                results[index] = float(value) * (metric.scale if metric.scale is not None else 1)
            elif isinstance(metric, contracts.AccountTableCountThresholdMetric):
                results[index] = int(value or 0)
    return results


def _resolve_account_logo_domain(account: Account) -> str | None:
    properties = account.properties
    return resolve_logo_domain(
        website_domain=properties.website_domain,
        email_domains=properties.email_domains,
    )


def query_accounts_table(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    selection: contracts.AccountTableColumnSelection,
    filters: tuple[contracts.AccountTableFilter, ...],
    sort: contracts.AccountTableSort | None,
    offset: int,
    limit: int,
    include_churned: bool = False,
    include_ignored: bool = False,
) -> contracts.AccountTablePage:
    custom_property_display_types = _validate_account_table_definitions(
        team_id=team_id,
        selection=selection,
        filters=filters,
        sort=sort,
    )

    queryset = _accounts_queryset(team_id, user_access_control)
    if not include_churned and not _filters_account_table_field(filters, contracts.AccountTableField.CHURNED_AT):
        queryset = queryset.filter(churned_at__isnull=True)
    if not include_ignored and not _filters_account_table_field(filters, contracts.AccountTableField.IGNORED_AT):
        queryset = queryset.filter(ignored_at__isnull=True)
    queryset = _apply_account_table_filters(
        queryset,
        team_id=team_id,
        filters=filters,
        custom_property_display_types=custom_property_display_types,
    )
    queryset = _apply_account_table_sort(
        queryset,
        team_id=team_id,
        sort=sort,
        custom_property_display_types=custom_property_display_types,
    )
    fetched_accounts = list(queryset[offset : offset + limit + 1])
    has_more = len(fetched_accounts) > limit
    accounts = fetched_accounts[:limit]
    account_ids = [account.id for account in accounts]

    tags_by_account: dict[UUID, list[str]] = {account_id: [] for account_id in account_ids}
    if selection.include_tags:
        for account_id, tag_name in (
            TaggedItem.objects.filter(account_id__in=account_ids)
            .order_by("tag__name")
            .values_list("account_id", "tag__name")
        ):
            tags_by_account[account_id].append(tag_name)

    note_counts_by_account: dict[UUID, int] = dict.fromkeys(account_ids, 0)
    if selection.include_note_count:
        for result in (
            ResourceNotebook.objects.filter(account_id__in=account_ids).values("account_id").annotate(count=Count("id"))
        ):
            note_counts_by_account[result["account_id"]] = result["count"]

    relationship_ids = selection.relationship_definition_ids
    sorted_relationship_ids = sorted(relationship_ids, key=lambda definition_id: definition_id.hex)
    relationships_by_account: dict[UUID, dict[UUID, list[int]]] = {
        account_id: {definition_id: [] for definition_id in sorted_relationship_ids} for account_id in account_ids
    }
    if relationship_ids:
        for account_id, definition_id, user_id in (
            AccountRelationship.objects.for_team(team_id)
            .filter(
                account_id__in=account_ids,
                definition_id__in=relationship_ids,
                ended_at__isnull=True,
                user_id__isnull=False,
            )
            .order_by("user_id")
            .values_list("account_id", "definition_id", "user_id")
        ):
            relationships_by_account[account_id][definition_id].append(user_id)

    custom_property_ids = selection.custom_property_definition_ids
    sorted_custom_property_ids = sorted(custom_property_ids, key=lambda definition_id: definition_id.hex)
    custom_properties_by_account: dict[UUID, dict[UUID, float | bool | str | None]] = {
        account_id: dict.fromkeys(sorted_custom_property_ids) for account_id in account_ids
    }
    if custom_property_ids:
        for value in CustomPropertyValue.objects.for_team(team_id).filter(
            account_id__in=account_ids,
            definition_id__in=custom_property_ids,
            is_deleted=False,
        ):
            custom_properties_by_account[value.account_id][value.definition_id] = _scalar_value_for_display_type(
                value, custom_property_display_types[value.definition_id]
            )

    history_windows = selection.custom_property_history_windows
    custom_property_history_by_account: dict[
        UUID, dict[UUID, list[contracts.AccountTableCustomPropertyHistoryPoint]]
    ] = {account_id: {definition_id: [] for definition_id in history_windows} for account_id in account_ids}
    if history_windows:
        now = timezone.now()
        history_filter = Q()
        for definition_id, window_days in history_windows.items():
            history_filter |= Q(definition_id=definition_id, created_at__gte=now - timedelta(days=window_days))
            history_filter |= Q(definition_id=definition_id, is_deleted=False)
        history_point_count = 0
        history_values = (
            CustomPropertyValue.objects.for_team(team_id)
            .filter(history_filter, account_id__in=account_ids, value_num__isnull=False)
            .order_by("created_at", "id")
            .iterator(chunk_size=2_000)
        )
        for value in history_values:
            history_point_count += 1
            if history_point_count > ACCOUNT_TABLE_MAX_HISTORY_POINTS:
                raise InvalidAccountTableColumn(
                    f"Account table queries support up to {ACCOUNT_TABLE_MAX_HISTORY_POINTS} history points."
                )
            assert value.value_num is not None
            custom_property_history_by_account[value.account_id][value.definition_id].append(
                contracts.AccountTableCustomPropertyHistoryPoint(
                    timestamp=value.created_at,
                    value=value.value_num,
                )
            )

    rows = [
        contracts.AccountTableRow(
            id=account.id,
            name=account.name,
            external_id=account.external_id,
            logo_domain=_resolve_account_logo_domain(account),
            account_fields=_account_table_field_values(account, selection.account_fields),
            tags=tags_by_account[account.id] if selection.include_tags else None,
            note_count=note_counts_by_account[account.id] if selection.include_note_count else None,
            relationships=relationships_by_account[account.id],
            custom_properties=custom_properties_by_account[account.id],
            custom_property_history=custom_property_history_by_account[account.id],
        )
        for account in accounts
    ]
    return contracts.AccountTablePage(rows=rows, has_more=has_more, limit=limit, offset=offset)


def list_accounts_for_view(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    offset: int,
    limit: int,
    search: str | None = None,
    tags: list[str] | None = None,
    all_roles_unassigned: bool = False,
    include_churned: bool = False,
    include_ignored: bool = False,
    ordering: str | None = None,
) -> tuple[list[contracts.AccountView], int]:
    """The accounts list endpoint, behind the facade: team + object-level access filtering,
    the search / tags / unassigned / ordering query filters, notebook + tag prefetching, and
    pagination. Returns ``(page, total_count)``. ``tags``/``ordering`` are pre-validated by
    the view; an empty ``tags`` list is treated as "no tag filter" (matches old behavior)."""
    queryset = _accounts_queryset(team_id, user_access_control).prefetch_related(
        Prefetch("notebooks", queryset=ResourceNotebook.objects.select_related("notebook")),
        Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
    )

    if not include_churned:
        queryset = queryset.filter(churned_at__isnull=True)
    if not include_ignored:
        queryset = queryset.filter(ignored_at__isnull=True)

    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(external_id__icontains=search))

    if tags:
        queryset = queryset.filter(tagged_items__tag__name__in=tags).distinct()

    # "Unassigned" means nobody actively holds any relationship on the account, matching the
    # accounts list HogQL runner's allRolesUnassigned.
    if all_roles_unassigned:
        queryset = queryset.exclude(
            id__in=AccountRelationship.objects.for_team(team_id)
            .filter(ended_at__isnull=True, user__isnull=False)
            .values("account_id")
        )

    queryset = queryset.order_by(ordering) if ordering else queryset.order_by("-created_at")

    total_count = queryset.count()
    page = list(queryset[offset : offset + limit])
    return [_to_account_view(a) for a in page], total_count


def get_account_for_view(
    *, team_id: int, account_id: str, user_access_control: "UserAccessControl", required_level: str | None
) -> contracts.AccountView:
    """Fetch one team-scoped account with tags + notebooks, enforcing object-level access.
    Raises ``Account.DoesNotExist`` (→ 404) / ``ResourceForbiddenError`` (→ 403)."""
    account = _get_account_for_detail(team_id, account_id)
    _enforce_object_access(account, user_access_control, required_level)
    return _to_account_view(account)


class _Unset(Enum):
    UNSET = "unset"


_UNSET = _Unset.UNSET


def _cap_to_field_length(field_name: str, value: str) -> str:
    max_length = cast(CharField, Account._meta.get_field(field_name)).max_length
    return value[:max_length]


def _enqueue_meeting_rematch(team_id: int, account_id: str) -> None:
    try:
        current_app.send_task(
            "customer_analytics.rematch_account_meetings",
            kwargs={"team_id": team_id, "account_id": account_id},
        )
    except Exception as error:
        capture_exception(error)


def update_account(
    account: Account,
    *,
    name: str | _Unset = _UNSET,
    external_id: str | None | _Unset = _UNSET,
    properties: "dict | _ModelAccountProperties | _Unset" = _UNSET,
    slack_summary_cadence: "str | None | _Unset" = _UNSET,
    churned_at: "datetime | None | _Unset" = _UNSET,
    allow_matching_updates: bool = False,
) -> Account:
    """Field-write primitive shared by every account update path. Only the fields passed are
    written; ``properties`` replaces the stored JSON wholesale. Product-internal — takes and
    returns the model, so it must not be called across the product boundary."""
    update_fields: list[str] = []
    matching_expanded = False
    if not isinstance(name, _Unset):
        account.name = _cap_to_field_length("name", name)
        update_fields.append("name")
    if not isinstance(external_id, _Unset):
        account.external_id = _cap_to_field_length("external_id", external_id) if external_id is not None else None
        update_fields.append("external_id")
    if not isinstance(properties, _Unset):
        previous_properties = account.properties
        validated_properties = _ModelAccountProperties.from_input(properties)
        known_emails_added = set(validated_properties.known_emails) - set(previous_properties.known_emails)
        email_domains_added = set(validated_properties.email_domains) - set(previous_properties.email_domains)
        matching_changed = set(validated_properties.known_emails) != set(previous_properties.known_emails) or set(
            validated_properties.email_domains
        ) != set(previous_properties.email_domains)
        if matching_changed and not allow_matching_updates:
            raise ResourceForbiddenError
        matching_expanded = bool(known_emails_added or email_domains_added)
        account._properties = validated_properties.model_dump(mode="json", exclude_unset=True)
        update_fields.append("_properties")
    if not isinstance(slack_summary_cadence, _Unset):
        account.slack_summary_cadence = slack_summary_cadence
        update_fields.append("slack_summary_cadence")
    if not isinstance(churned_at, _Unset):
        account.churned_at = churned_at
        update_fields.append("churned_at")
    if update_fields:
        account.save(update_fields=update_fields)
    if matching_expanded:
        transaction.on_commit(lambda: _enqueue_meeting_rematch(account.team_id, str(account.id)))
    if "external_id" in update_fields or "_properties" in update_fields:
        schedule_email_thread_link_recalculation(account.team_id)
    return account


def create_account(
    *,
    team: Team,
    name: str,
    created_by: "User | None" = None,
    external_id: str | None = None,
    properties: "dict | _ModelAccountProperties | None" = None,
    tags: list[str] | None = None,
    slack_summary_cadence: str | None = None,
    churned_at: datetime | None = None,
    was_impersonated: bool = False,
    trigger: Trigger | None = None,
) -> Account:
    """The single account-creation write path: validates properties, sets tags, and logs
    activity. Product-internal — it returns the model, so it must not be called across the
    product boundary.
    Raises ``AccountPropertiesValidationError`` / ``AccountConflictError``."""
    try:
        with transaction.atomic():
            validated = _ModelAccountProperties.from_input(properties or {})
            account = Account.objects.unscoped().create(
                team=team,
                created_by=created_by,
                name=_cap_to_field_length("name", name),
                external_id=_cap_to_field_length("external_id", external_id) if external_id is not None else None,
                _properties=validated.model_dump(mode="json", exclude_unset=True),
                slack_summary_cadence=slack_summary_cadence,
                churned_at=churned_at,
            )
            _set_tags(tags, account, actor=created_by)
    except PydanticValidationError as exc:
        raise AccountPropertiesValidationError(_format_pydantic_errors(exc))
    except IntegrityError:
        raise AccountConflictError("An account with this external_id already exists for this team.")
    _log_activity_swallowing(
        instance=account,
        scope="Account",
        activity="created",
        name=account.name,
        organization_id=team.organization_id,
        team_id=team.pk,
        user=created_by,
        was_impersonated=was_impersonated,
        trigger=trigger,
    )
    schedule_email_thread_link_recalculation(team.pk)
    return account


def create_account_for_view(
    *,
    team: Team,
    input: contracts.CreateAccountInput,
    user: "User",
    was_impersonated: bool,
) -> contracts.AccountView:
    account = create_account(
        team=team,
        created_by=user,
        name=input.name,
        external_id=input.external_id,
        properties=input.properties,
        tags=input.tags,
        slack_summary_cadence=input.slack_summary_cadence,
        churned_at=input.churned_at,
        was_impersonated=was_impersonated,
    )
    return _to_account_view(account)


def update_account_for_view(
    *,
    team_id: int,
    account_id: str,
    input: contracts.UpdateAccountInput,
    user_access_control: "UserAccessControl",
    required_level: str | None,
    organization_id,
    user: "User",
    was_impersonated: bool,
    allow_matching_updates: bool = False,
) -> contracts.AccountView:
    account = _get_account_for_detail(team_id, account_id)
    _enforce_object_access(account, user_access_control, required_level)
    previous = Account.objects.unscoped().get(pk=account.pk)

    update_kwargs: dict[str, Any] = {}
    if input.name is not None:
        update_kwargs["name"] = input.name
    if input.external_id_provided:
        update_kwargs["external_id"] = input.external_id
    if input.properties_provided:
        update_kwargs["properties"] = input.properties if input.properties is not None else {}
    if input.slack_summary_cadence_provided:
        update_kwargs["slack_summary_cadence"] = input.slack_summary_cadence
    if input.churned_at_provided:
        update_kwargs["churned_at"] = input.churned_at
    update_kwargs["allow_matching_updates"] = allow_matching_updates

    try:
        with transaction.atomic():
            account = update_account(account, **update_kwargs)
            _set_tags(input.tags, account, actor=user)
            if input.external_id_provided and account.external_id != previous.external_id:
                # The external_id is the account's group key — every stream filtering on
                # the old key must be rebuilt or it keeps streaming the stale key's events.
                for stream in _event_streams_containing_account(account):
                    sync_event_stream_destination(stream, team=account.team, user=user)
    except PydanticValidationError as exc:
        raise AccountPropertiesValidationError(_format_pydantic_errors(exc))
    except IntegrityError:
        raise AccountConflictError("An account with this external_id already exists for this team.")
    _log_activity_swallowing(
        instance=account,
        scope="Account",
        activity="updated",
        name=account.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        previous=previous,
    )
    # Off-to-on only: the coordinator picks a mid-flight cadence change up within the hour,
    # and one backfill per switch is LLM spend nobody asked for.
    if not previous.slack_summary_cadence and account.slack_summary_cadence:
        _dispatch_initial_channel_summary(account)
    return _to_account_view(account)


# Roughly 70 accounts opting into a daily cadence in one day, far above real use.
CHANNEL_SUMMARY_BACKFILL_DAILY_CAP = 500


def _reserve_backfill_budget(team_id: int, requested: int) -> int:
    """How many of ``requested`` backfill dispatches this team may still start today.

    The coordinator throttles itself with per-run caps, but these dispatches are driven by
    an API call, so one caller opting in many channel-bound accounts could otherwise start
    unbounded LLM work in a burst. ``cache.incr`` is atomic, so parallel requests cannot all
    slip under the ceiling. Whatever this refuses, the coordinator still summarizes on
    schedule.
    """
    window = int(datetime.now(UTC).timestamp()) // 86400
    key = f"ca_channel_summary_backfills:{team_id}:{window}"
    cache.add(key, 0, timeout=86400)
    try:
        used = cache.incr(key, requested)
    except ValueError:
        # The key expired between add and incr; this request is the window's first.
        used = requested
    allowed = requested - max(0, used - CHANNEL_SUMMARY_BACKFILL_DAILY_CAP)
    return max(0, allowed)


def _dispatch_initial_channel_summary(account: Account) -> None:
    cadence = account.slack_summary_cadence
    slack_channel_id = (account._properties or {}).get("slack_channel_id")
    if not cadence or not slack_channel_id:
        return
    periods = _channel_summaries_logic.get_initial_summary_periods(cadence, timezone.now(), account.team.timezone_info)
    allowed = _reserve_backfill_budget(account.team_id, len(periods))
    if allowed < len(periods):
        logger.warning(
            "channel_summary_backfill_throttled",
            team_id=account.team_id,
            requested=len(periods),
            allowed=allowed,
        )
    # Newest first, so a partly-throttled backfill keeps the periods a user looks at first.
    for period in sorted(periods, key=lambda p: p.start, reverse=True)[:allowed]:
        try:
            trigger_immediate_channel_summary(
                team_id=account.team_id,
                account_id=str(account.id),
                account_name=account.name,
                slack_channel_id=slack_channel_id,
                cadence=cadence,
                period_start=period.start,
                period_end=period.end,
            )
        except Exception as e:
            # Per period, so one bad dispatch doesn't drop the rest.
            capture_exception(
                e,
                {
                    "team_id": account.team_id,
                    "account_id": str(account.id),
                    "period_start": period.start.isoformat(),
                },
            )


def delete_account_for_view(
    *,
    team_id: int,
    account_id: str,
    user_access_control: "UserAccessControl",
    required_level: str | None,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> None:
    account = _get_account_for_detail(team_id, account_id)
    _enforce_object_access(account, user_access_control, required_level)
    _log_activity_swallowing(
        instance=account,
        scope="Account",
        activity="deleted",
        name=account.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
    )
    with transaction.atomic():
        # Streams referencing this account must be captured before the delete cascades
        # their membership rows away, then resynced so the account's group key doesn't
        # linger in a Slack destination filter.
        streams = _event_streams_containing_account(account)
        team = account.team
        account.delete()
        schedule_email_thread_link_recalculation(team_id)
        for stream in streams:
            sync_event_stream_destination(stream, team=team, user=user)


def _get_account_for_detail(team_id: int, account_id: str) -> Account:
    """Team-scoped account fetch for detail/write paths (object-level access is enforced
    separately). Prefetches notebooks + tags so the returned view renders without extra
    queries, matching the old viewset's ``safely_get_queryset`` + tag-mixin prefetch.
    Raises ``Account.DoesNotExist`` when not found in the team."""
    queryset = (
        Account.objects.unscoped()
        .filter(team_id=team_id)
        .prefetch_related(
            Prefetch("notebooks", queryset=ResourceNotebook.objects.select_related("notebook")),
            Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
        )
    )
    return _get_object_or_raise(queryset, account_id, Account)


# --- AccountNotebook (nested under an account) ---


def _to_user_basic_info(user: "User | None") -> contracts.UserBasicInfo | None:
    # None when the notebook has no creator/modifier — the old nested
    # ``UserBasicSerializer`` rendered ``null`` for a null FK, so preserve that.
    if user is None:
        return None
    return contracts.UserBasicInfo(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _notebook_user_to_basic_info(
    user: "notebook_contracts.NotebookUserInfo | None",
) -> contracts.UserBasicInfo | None:
    if user is None:
        return None
    return contracts.UserBasicInfo(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _to_account_notebook_view(notebook: "notebook_contracts.AccountNotebook") -> contracts.AccountNotebookView:
    return contracts.AccountNotebookView(
        id=notebook.id,
        short_id=notebook.short_id,
        title=notebook.title,
        content=notebook.content,
        text_content=notebook.text_content,
        created_at=notebook.created_at,
        created_by=_notebook_user_to_basic_info(notebook.created_by),
        last_modified_at=notebook.last_modified_at,
        last_modified_by=_notebook_user_to_basic_info(notebook.last_modified_by),
    )


def get_accessible_account_id(team_id: int, account_id: str, user_access_control: "UserAccessControl") -> str | None:
    """The account_id when the caller has object-level access to that team-scoped account,
    else None — backs the notebook viewset's parent-account gate (object denial → 404,
    via filtering rather than a permission check)."""
    queryset = user_access_control.filter_queryset_by_access_level(Account.objects.unscoped().filter(team_id=team_id))
    try:
        account = queryset.filter(id=account_id).first()
    except (ValidationError, ValueError):
        return None
    return str(account.id) if account is not None else None


def list_account_channel_summaries(
    team_id: int,
    account_id: str,
    user_access_control: "UserAccessControl",
    *,
    offset: int,
    limit: int,
) -> tuple[list[contracts.AccountChannelSummaryView], int] | None:
    """Stored Slack channel summaries for an accessible account, newest period first.

    Returns ``(page, total_count)``, or None when the parent account isn't accessible (→ 404)."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    queryset = (
        AccountChannelSummary.objects.for_team(team_id)
        .filter(account_id=account_id)
        .order_by("-period_start", "-generated_at")
    )
    total_count = queryset.count()
    return [_to_channel_summary_view(s) for s in queryset[offset : offset + limit]], total_count


def _to_channel_summary_view(summary: AccountChannelSummary) -> contracts.AccountChannelSummaryView:
    return contracts.AccountChannelSummaryView(
        id=summary.id,
        slack_channel_id=summary.slack_channel_id,
        cadence=summary.cadence,
        period_start=summary.period_start,
        period_end=summary.period_end,
        content=summary.content,
        message_count=summary.message_count,
        messages=summary.messages,
        generated_at=summary.generated_at,
    )


def list_accounts_due_for_slack_summary(now: datetime | None = None) -> list[contracts.AccountDueForSlackSummary]:
    """Accounts opted into periodic Slack channel summaries whose last closed period has no
    stored summary yet. Cross-team — backs the conversations summary coordinator.

    Due means: a cadence is set, a Slack channel is bound, and no summary row exists for
    ``(account, cadence, period_start)`` where the period is the last closed calendar window
    in the account team's timezone. A cadence change mid-period only ever looks at the
    current cadence's own last closed window — no retro-generation.
    """
    now = now or timezone.now()
    candidates: list[contracts.AccountDueForSlackSummary] = []
    for account in (
        Account.objects.unscoped().filter(slack_summary_cadence__isnull=False).select_related("team").iterator()
    ):
        # Raw dict read: one account with stored properties that no longer validate must not
        # take the whole coordinator scan down.
        slack_channel_id = (account._properties or {}).get("slack_channel_id")
        cadence = account.slack_summary_cadence
        if not slack_channel_id or not cadence:
            continue
        period = _channel_summaries_logic.get_last_closed_period(cadence, now, account.team.timezone_info)
        candidates.append(
            contracts.AccountDueForSlackSummary(
                team_id=account.team_id,
                account_id=str(account.id),
                account_name=account.name,
                slack_channel_id=slack_channel_id,
                cadence=cadence,
                period_start=period.start,
                period_end=period.end,
            )
        )
    if not candidates:
        return []
    existing = set(
        AccountChannelSummary.objects.unscoped()
        .filter(
            account_id__in=[c.account_id for c in candidates],
            period_start__in={c.period_start for c in candidates},
        )
        .values_list("account_id", "cadence", "period_start")
    )
    return [c for c in candidates if (UUID(c.account_id), c.cadence, c.period_start) not in existing]


def get_account_slack_summary_binding(team_id: int, account_id: str) -> contracts.AccountSlackSummaryBinding | None:
    """The account's current summary cadence and channel binding, or None when the
    account is gone or no longer opted in. Backs the summary activity's recheck just
    before messages are fetched and sent to the LLM: consent or binding changes after
    coordinator dispatch must cancel the queued summary."""
    account = Account.objects.for_team(team_id).filter(id=account_id).first()
    if account is None or not account.slack_summary_cadence:
        return None
    slack_channel_id = (account._properties or {}).get("slack_channel_id")
    if not slack_channel_id:
        return None
    return contracts.AccountSlackSummaryBinding(
        cadence=account.slack_summary_cadence, slack_channel_id=slack_channel_id
    )


def record_channel_summary(
    *,
    team_id: int,
    account_id: str,
    slack_channel_id: str,
    cadence: str,
    period_start: datetime,
    period_end: datetime,
    content: str,
    message_count: int,
    messages: list[dict] | None = None,
    model_name: str = "",
) -> str | None:
    """Store a finished channel summary pushed in by the conversations pipeline.

    ``messages`` is the per-message audit metadata ([{author, sent_at, permalink}]),
    never message text.

    Idempotent on ``(team, account, cadence, period_start)``: a retry or overlapping run
    resolves to the existing row's id instead of double-writing. Returns None when the
    account no longer exists (deleted mid-flight) — the period's summary is simply dropped.
    """
    if not Account.objects.for_team(team_id).filter(id=account_id).exists():
        return None
    try:
        # atomic() so the duplicate-key error rolls back to a savepoint and the
        # existing-row lookup below still has a usable connection.
        with transaction.atomic():
            summary = AccountChannelSummary.objects.for_team(team_id).create(
                team_id=team_id,
                account_id=account_id,
                slack_channel_id=slack_channel_id,
                cadence=cadence,
                period_start=period_start,
                period_end=period_end,
                content=content,
                message_count=message_count,
                messages=messages or [],
                model_name=model_name,
            )
    except IntegrityError:
        existing = (
            AccountChannelSummary.objects.for_team(team_id)
            .filter(account_id=account_id, cadence=cadence, period_start=period_start)
            .first()
        )
        return str(existing.id) if existing is not None else None
    return str(summary.id)


def get_account_support_tickets(
    team_id: int,
    account_id: str,
    user_access_control: "UserAccessControl",
    *,
    limit: int = 50,
) -> list[TicketSummary] | None:
    """Support tickets (from the conversations product) for an accessible account, newest activity
    first. None when the parent account isn't accessible (→ 404); an empty list when the account
    has no linked customer org key, or has one but no matching tickets.

    Raises :class:`ResourceForbiddenError` (→ 403) when the caller can read the account but not
    tickets — this endpoint is authorized as ``account`` while the payload is ticket content, so
    the ``ticket`` resource has to be gated separately or this path bypasses its RBAC."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    if not user_access_control.check_access_level_for_resource("ticket", "viewer"):
        raise ResourceForbiddenError()
    account = _resolve_account(team_id, account_id=account_id)
    if account is None or not account.external_id:
        return []
    return list_account_tickets(team_id, account.external_id, user_access_control, limit=limit)


def get_account_support_ticket_messages(
    team_id: int,
    account_id: str,
    ticket_id: str,
    user_access_control: "UserAccessControl",
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[SupportTicketMessage], int] | None:
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    if not user_access_control.check_access_level_for_resource("ticket", "viewer"):
        raise ResourceForbiddenError()
    account = _resolve_account(team_id, account_id=account_id)
    if account is None or not account.external_id:
        return None
    return list_account_ticket_messages(
        team_id,
        account.external_id,
        ticket_id,
        user_access_control,
        offset=offset,
        limit=limit,
    )


def get_account_email_threads(
    team_id: int,
    account_id: str,
    user_access_control: "UserAccessControl",
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AccountEmailThreadSummary], int] | None:
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    if not user_access_control.check_access_level_for_resource("ticket", "viewer"):
        raise ResourceForbiddenError()
    return list_account_email_threads(team_id, account_id, offset=offset, limit=limit)


def get_account_email_thread_messages(
    team_id: int,
    account_id: str,
    thread_id: str,
    user_access_control: "UserAccessControl",
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AccountEmailThreadMessage], int] | None:
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    if not user_access_control.check_access_level_for_resource("ticket", "viewer"):
        raise ResourceForbiddenError()
    return list_account_email_thread_messages(team_id, account_id, thread_id, offset=offset, limit=limit)


AccountTrackRuleValidationError = _account_track_rules_logic.AccountTrackRuleValidationError
AccountTrackRuleVersionConflict = _account_track_rules_logic.AccountTrackRuleVersionConflict
AccountTrackRuleRunError = _account_track_rules_logic.AccountTrackRuleRunError


class AccountTrackRuleRunAlreadyActive(ValueError):
    pass


def get_account_track_rules(team_id: int) -> contracts.AccountTrackRulesConfig:
    return _account_track_rules_logic.get_account_track_rules(team_id)


def update_account_track_rules(
    *,
    team_id: int,
    raw_config: dict[str, Any],
    user: "User",
    organization_id: UUID,
    was_impersonated: bool,
) -> contracts.AccountTrackRulesConfig:
    return _account_track_rules_logic.update_account_track_rules(
        team_id=team_id,
        raw_config=raw_config,
        user=user,
        organization_id=organization_id,
        was_impersonated=was_impersonated,
    )


def preview_account_track_rules(
    team_id: int, raw_config: dict[str, Any] | None = None
) -> contracts.AccountTrackRulePreview:
    return _account_track_rules_logic.preview_account_track_rules(team_id, raw_config)


def list_account_track_rule_runs(
    team_id: int, *, offset: int, limit: int
) -> tuple[list[contracts.AccountTrackRuleRunView], int]:
    return _account_track_rules_logic.list_account_track_rule_runs(team_id, offset=offset, limit=limit)


def trigger_account_track_rule_run(
    *,
    team_id: int,
    idempotency_key: UUID,
    user_id: int,
) -> tuple[contracts.AccountTrackRuleRunView, bool]:
    run, created = _account_track_rules_logic.create_account_track_rule_run(
        team_id=team_id,
        idempotency_key=idempotency_key,
        user_id=user_id,
    )
    if not created:
        return _account_track_rules_logic.to_run_view(run), False

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.customer_analytics.backend.temporal.account_track_rules import (  # noqa: PLC0415
        AccountTrackRuleEvaluationInput,
        AccountTrackRuleEvaluationWorkflow,
        account_track_rule_workflow_id,
    )

    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                AccountTrackRuleEvaluationWorkflow.run,
                AccountTrackRuleEvaluationInput(
                    team_id=team_id,
                    run_id=str(run.id),
                    config_version=run.config_version,
                ),
                id=account_track_rule_workflow_id(team_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )
    except WorkflowAlreadyStartedError as error:
        _account_track_rules_logic.fail_account_track_rule_run(team_id, run.id)
        raise AccountTrackRuleRunAlreadyActive("Another Track Rules run is already in progress.") from error
    except Exception:
        _account_track_rules_logic.fail_account_track_rule_run(team_id, run.id)
        raise
    return _account_track_rules_logic.to_run_view(run), True


def list_calendar_sync_statuses(team_id: int) -> list[contracts.CalendarSyncStatus]:
    """Sync state of every connected calendar for the team: last completed sync and
    whether a run is currently in flight (started but not finished, within the sync
    activity's timeout — a run past it is considered dead, not running)."""
    from products.customer_analytics.backend.logic.calendar_sync import (  # noqa: PLC0415 — keeps requests/HogQL layers off the import path
        LAST_SYNCED_AT_CONFIG_KEY,
        SYNC_STALE_AFTER,
        SYNC_STARTED_AT_CONFIG_KEY,
    )

    statuses = []
    for integration in Integration.objects.filter(team_id=team_id, kind="google-calendar").order_by("id"):
        config = integration.config or {}
        last_synced_at = _parse_datetime(config.get(LAST_SYNCED_AT_CONFIG_KEY))
        started_at = _parse_datetime(config.get(SYNC_STARTED_AT_CONFIG_KEY))
        is_syncing = bool(
            started_at
            and (last_synced_at is None or started_at > last_synced_at)
            and started_at > timezone.now() - SYNC_STALE_AFTER
        )
        statuses.append(
            contracts.CalendarSyncStatus(
                integration_id=integration.id,
                last_synced_at=last_synced_at,
                is_syncing=is_syncing,
            )
        )
    return statuses


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def trigger_calendar_sync(team_id: int, integration_id: int) -> str | None:
    """Start the calendar-sync workflow for one connected calendar, outside the hourly
    schedule. Returns 'started', 'already_running' (a sync for this calendar is in
    flight; the workflow id is deterministic per integration), or None when the
    integration doesn't exist for this team (→ 404)."""
    if not Integration.objects.filter(id=integration_id, team_id=team_id, kind="google-calendar").exists():
        return None

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415 — keeps temporal off the import path

    from products.customer_analytics.backend.temporal.calendar_sync import (  # noqa: PLC0415 — same
        CalendarSyncInput,
        CalendarSyncWorkflow,
    )

    client = sync_connect()
    try:
        asyncio.run(
            client.start_workflow(
                CalendarSyncWorkflow.run,
                CalendarSyncInput(integration_id=integration_id, team_id=team_id),
                id=f"google-calendar-sync-{integration_id}",
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )
    except WorkflowAlreadyStartedError:
        return "already_running"
    return "started"


def list_account_meetings(
    team_id: int,
    account_id: str,
    user_access_control: "UserAccessControl",
    *,
    offset: int = 0,
    limit: int = 100,
    search: str | None = None,
) -> tuple[list[contracts.MeetingView], int] | None:
    """Synced calendar meetings for an accessible account, newest first, optionally
    filtered by ``search`` (title or attendee email/name). None when the account isn't
    accessible (→ 404)."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    queryset = Meeting.objects.for_team(team_id).filter(account_id=account_id)
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(participants__email__icontains=search)
            | Q(participants__display_name__icontains=search)
        ).distinct()
    count = queryset.count()
    meetings = list(queryset.order_by("-start_time").prefetch_related("participants")[offset : offset + limit])

    from products.customer_analytics.backend.logic.gong import (  # noqa: PLC0415 — keeps HogQL off the facade import path
        get_gong_urls_by_meeting_id,
    )

    team = user_access_control.team
    if team is None or team.id != team_id:
        team = Team.objects.get(id=team_id)
    gong_urls_by_meeting_id = get_gong_urls_by_meeting_id(team=team, user=user_access_control.user, meetings=meetings)

    views = [
        contracts.MeetingView(
            id=meeting.id,
            title=meeting.title,
            gong_url=gong_urls_by_meeting_id.get(meeting.id),
            start_time=meeting.start_time,
            end_time=meeting.end_time,
            organizer_email=meeting.organizer_email,
            status=meeting.status,
            participants=[
                contracts.MeetingParticipantView(
                    email=participant.email,
                    display_name=participant.display_name,
                    response_status=participant.response_status,
                    is_organizer=participant.is_organizer,
                    person_id=participant.person_id,
                )
                for participant in meeting.participants.all()
            ],
        )
        for meeting in meetings
    ]
    return views, count


def list_account_notebooks(
    team_id: int,
    account_id: str,
    user_access_control: "UserAccessControl",
    *,
    search: str | None = None,
    order: str | None = None,
) -> list[contracts.AccountNotebookView] | None:
    """Internal notebooks linked to an accessible account. Optionally full-text filtered by
    ``search`` (title + content) and sorted by ``order`` (creation date or author); defaults to
    newest first. None when the parent account isn't accessible (→ 404)."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    return [
        _to_account_notebook_view(n) for n in notebooks.list_account_notebooks(account_id, search=search, order=order)
    ]


def list_account_notes_for_view(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    offset: int,
    limit: int,
    search: str | None = None,
    account_id: UUID | str | None = None,
    created_by_ids: list[int] | None = None,
    assigned_to_ids: list[int] | None = None,
) -> tuple[list[contracts.AccountNoteView], int]:
    """Team-wide account notes (internal notebooks linked to accounts), newest-modified first,
    restricted to accounts the caller can read. ``search`` matches note title/content (full-text)
    and account name (substring). ``account_id`` narrows to one account, ``created_by_ids`` to
    notes authored by the given users, ``assigned_to_ids`` to notes on accounts where one of the
    given users actively holds a relationship. Returns ``(page, total_count)``."""
    accounts = _accounts_queryset(team_id, user_access_control)
    if assigned_to_ids:
        # "Assigned to" means any active relationship, matching the accounts list HogQL
        # runner's assignedToUserIds.
        accounts = accounts.filter(
            id__in=AccountRelationship.objects.for_team(team_id)
            .filter(ended_at__isnull=True, user_id__in=assigned_to_ids)
            .values("account_id")
        )
    accessible_account_ids = accounts.values_list("id", flat=True)
    notes, count = notebooks.list_team_account_notes(
        team_id,
        account_ids=accessible_account_ids,
        account_id=account_id,
        created_by_ids=created_by_ids,
        search=search,
        offset=offset,
        limit=limit,
    )
    return [
        contracts.AccountNoteView(
            short_id=note.short_id,
            title=note.title,
            created_at=note.created_at,
            last_modified_at=note.last_modified_at,
            account_id=note.account_id,
            account_name=note.account_name,
            created_by=_notebook_user_to_basic_info(note.created_by),
        )
        for note in notes
    ], count


def get_account_notebook(
    team_id: int, account_id: str, short_id: str, user_access_control: "UserAccessControl"
) -> contracts.AccountNotebookView | None:
    """One internal notebook linked to an accessible account. None when the account isn't
    accessible or no such linked notebook exists (→ 404)."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    notebook = notebooks.get_account_notebook(account_id, short_id)
    return _to_account_notebook_view(notebook) if notebook is not None else None


def create_account_notebook(
    *,
    team_id: int,
    team,
    account_id: str,
    input: contracts.CreateAccountNotebookInput,
    user: "User",
    user_access_control: "UserAccessControl",
) -> contracts.AccountNotebookView | None:
    """Create an internal notebook and link it to an accessible account. None when the
    parent account isn't accessible (→ 404). The view supplies ``synthesized_content``
    (markdown→tiptap) so the ``ee.hogai`` helper stays off the facade import path."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return None
    content = input.synthesized_content if input.synthesized_content is not None else input.content
    created = notebooks.create_account_notebook(
        team_id,
        account_id,
        title=input.title,
        content=content,
        text_content=input.text_content,
        created_by_id=user.id,
        last_modified_by_id=user.id,
    )
    # The creator is also the (only) modifier of a just-created notebook, so the user the
    # caller already holds is both `created_by` and `last_modified_by` — no extra fetch.
    author = _to_user_basic_info(user)
    return contracts.AccountNotebookView(
        id=created.id,
        short_id=created.short_id,
        title=created.title,
        content=created.content,
        text_content=created.text_content,
        created_at=created.created_at,
        created_by=author,
        last_modified_at=created.last_modified_at,
        last_modified_by=author,
    )


def delete_account_notebook(
    *, team_id: int, account_id: str, short_id: str, user_access_control: "UserAccessControl"
) -> bool:
    """Delete an internal notebook linked to an accessible account. False when the account
    isn't accessible or no such notebook exists (→ 404)."""
    if get_accessible_account_id(team_id, account_id, user_access_control) is None:
        return False
    return notebooks.delete_account_notebook(account_id, short_id)


# --- shared resolution / access helpers for the CRUD paths ---


def _get_team_scoped(model, team_id: int, pk: str | UUID):
    """Fetch a team-scoped row by pk, or None (malformed/absent). Used by the
    profile-config path, whose old viewset returned 404 for both."""
    try:
        return model.objects.filter(team_id=team_id).get(pk=pk)
    except (model.DoesNotExist, ValidationError, ValueError):
        return None


def _get_object_or_raise(queryset, pk: str, model):
    """Fetch by pk from an already-scoped queryset, raising ``model.DoesNotExist`` for
    absent/malformed ids (the view maps that to 404)."""
    try:
        obj = queryset.filter(pk=pk).first()
    except (ValidationError, ValueError):
        raise model.DoesNotExist()
    if obj is None:
        raise model.DoesNotExist()
    return obj


def _enforce_object_access(obj, user_access_control: "UserAccessControl", required_level: str | None) -> None:
    """Object-level access gate matching ``AccessControlPermission.has_object_permission``:
    raise ``ResourceForbiddenError`` (→ 403) when the caller lacks ``required_level`` on the
    object. The view computes ``required_level`` from the HTTP method (viewer / editor), and
    passes ``None`` when the permission layer would skip the object check (service auth) — in
    which case the gate is a no-op, exactly like ``has_object_permission`` returning early."""
    if required_level is None:
        return
    if not user_access_control.check_access_level_for_object(obj, required_level=required_level):  # type: ignore[arg-type]
        raise ResourceForbiddenError()


# --- Custom property values ---

# Re-exported from logic so the presentation layer can catch them — the import-linter forbids
# presentation importing logic directly, so these errors are part of the facade's surface.
CustomPropertyDefinitionNotFound = _custom_property_values_logic.CustomPropertyDefinitionNotFound
CustomPropertyValueConflict = _custom_property_values_logic.CustomPropertyValueConflict
InvalidCustomPropertyValue = _custom_property_values_logic.InvalidCustomPropertyValue


def _source_backed_definition_ids(team_id: int, definition_ids: Iterable[str | UUID]) -> set[UUID]:
    """Definition ids from ``definition_ids`` that are backed by a view sync. Manual writes to these
    are closed at the API layer (the sync writes them through the logic directly), so callers can't
    fight the sync over the value."""
    return set(
        CustomPropertySource.objects.for_team(team_id)
        .filter(definition_id__in=definition_ids)
        .values_list("definition_id", flat=True)
    )


class CustomPropertyValueSourceManaged(Exception):
    """Raised when a manual write targets a source-backed definition. The view sync writes such
    definitions through the logic layer directly; the manual API path is closed so the two can't
    fight over the value (→ 400)."""


def _to_custom_property_value(row: "CustomPropertyValue") -> contracts.CustomPropertyValue:
    return contracts.CustomPropertyValue(
        id=row.id,
        account_id=row.account_id,
        definition_id=row.definition_id,
        value=_custom_property_values_logic.value_of(row),
        created_at=row.created_at,
        created_by_id=row.created_by_id,
    )


def set_custom_property_value(
    team_id: int,
    account_id: str | UUID,
    definition_id: str | UUID,
    value: Any,
    *,
    actor: "User | None" = None,
) -> contracts.CustomPropertyValue:
    if _source_backed_definition_ids(team_id, [definition_id]):
        raise CustomPropertyValueSourceManaged(
            "This custom property is managed by a data warehouse source and can't be set manually."
        )
    row = _custom_property_values_logic.set_custom_property_value(
        team_id=team_id,
        account_id=account_id,
        definition_id=definition_id,
        value=value,
        created_by_id=actor.id if actor else None,
        actor=actor,
    )
    return _to_custom_property_value(row)


def record_last_slack_message_at(*, team_id: int, account_id: str | UUID, timestamp: datetime) -> bool:
    """Record when a customer last messaged in the Slack channel bound to `account_id`.

    For conversations, which sees the messages. Throttled and self-creating — see the logic
    function. Returns whether the stored value moved.
    """
    return _custom_property_values_logic.record_last_slack_message_at(
        team_id=team_id, account_id=account_id, timestamp=timestamp
    )


def list_active_custom_property_values(team_id: int, account_id: str | UUID) -> list[contracts.CustomPropertyValue]:
    """The account's current (non-deleted) custom property values as contracts, newest first."""
    rows = _custom_property_values_logic.list_active_custom_property_values(team_id=team_id, account_id=account_id)
    return [_to_custom_property_value(row) for row in rows]


# --- Account relationships ---


class AccountRelationshipDefinitionConflictError(Exception):
    """Raised when a relationship definition violates the per-team unique name constraint."""


def _to_account_relationship_definition(
    definition: AccountRelationshipDefinition,
) -> contracts.AccountRelationshipDefinition:
    return contracts.AccountRelationshipDefinition(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        is_single_holder=definition.is_single_holder,
    )


def _to_account_relationship(relationship: AccountRelationship) -> contracts.AccountRelationship:
    user = relationship.user
    return contracts.AccountRelationship(
        id=relationship.id,
        definition=_to_account_relationship_definition(relationship.definition),
        user=contracts.AccountAssignment(id=user.id, email=user.email) if user is not None else None,
        started_at=relationship.started_at,
        ended_at=relationship.ended_at,
    )


def list_account_relationship_definitions(
    team_id: int, offset: int = 0, limit: int = 100
) -> tuple[list[contracts.AccountRelationshipDefinition], int]:
    queryset = AccountRelationshipDefinition.objects.for_team(team_id).order_by("name")
    total_count = queryset.count()
    page = queryset[offset : offset + limit]
    return [_to_account_relationship_definition(definition) for definition in page], total_count


def create_account_relationship_definition(
    *,
    team_id: int,
    name: str,
    description: str | None = None,
    is_single_holder: bool = True,
    created_by: "User",
) -> contracts.AccountRelationshipDefinition:
    try:
        definition = AccountRelationshipDefinition.objects.for_team(team_id).create(
            team_id=team_id,
            name=name,
            description=description,
            is_single_holder=is_single_holder,
            created_by=created_by,
        )
    except IntegrityError:
        raise AccountRelationshipDefinitionConflictError(
            "A relationship definition with this name already exists for this team."
        )
    return _to_account_relationship_definition(definition)


def get_account_relationship_definition(
    team_id: int, definition_id: str | UUID
) -> contracts.AccountRelationshipDefinition | None:
    definition = AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).first()
    if definition is None:
        return None
    return _to_account_relationship_definition(definition)


def update_account_relationship_definition(
    *, team_id: int, definition_id: str | UUID, fields: dict[str, Any]
) -> contracts.AccountRelationshipDefinition | None:
    definition = AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).first()
    if definition is None:
        return None
    for attr, value in fields.items():
        setattr(definition, attr, value)
    try:
        definition.save()
    except IntegrityError:
        raise AccountRelationshipDefinitionConflictError(
            "A relationship definition with this name already exists for this team."
        )
    return _to_account_relationship_definition(definition)


def delete_account_relationship_definition(*, team_id: int, definition_id: str | UUID) -> bool:
    """Hard-deletes the definition and (by cascade) its assignment history. Returns False when
    no definition matches the id for this team (→ 404)."""
    deleted, _ = AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).delete()
    return deleted > 0


def list_account_relationships(
    *, team_id: int, account_id: str | UUID, include_history: bool = False
) -> list[contracts.AccountRelationship]:
    """The account's active relationships, or its full assignment timeline with ``include_history``."""
    queryset = (
        AccountRelationship.objects.for_team(team_id)
        .filter(account_id=account_id)
        .select_related("definition", "user")
        .order_by("definition__name", "-started_at")
    )
    if not include_history:
        queryset = queryset.filter(ended_at__isnull=True)
    return [_to_account_relationship(relationship) for relationship in queryset]


class AccountRelationshipDefinitionNotFound(Exception):
    pass


class AccountRelationshipAssigneeNotInOrganization(Exception):
    pass


def assign_account_relationship(
    *, team_id: int, account_id: str | UUID, definition_id: str | UUID, user_id: int, created_by: "User"
) -> contracts.AccountRelationship:
    """Assign a user to an account relationship. Single-holder definitions hand off — the
    previous active assignment is ended in the same transaction. Idempotent when the user
    already actively holds the relationship.

    Raises ``Account_DoesNotExist`` (→ 404), ``AccountRelationshipDefinitionNotFound`` and
    ``AccountRelationshipAssigneeNotInOrganization`` (→ 400).
    """
    account = Account.objects.for_team(team_id).select_related("team").get(id=account_id)
    definition = AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).first()
    if definition is None:
        raise AccountRelationshipDefinitionNotFound(str(definition_id))
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization_id=account.team.organization_id, user_id=user_id)
        .first()
    )
    if membership is None:
        raise AccountRelationshipAssigneeNotInOrganization(str(user_id))
    relationship = _relationships_logic.assign(
        team_id=team_id, account=account, definition=definition, user=membership.user, created_by=created_by
    )
    return _to_account_relationship(relationship)


def end_account_relationship(
    *,
    team_id: int,
    account_id: str | UUID,
    relationship_id: str | UUID,
    actor: "User | None" = None,
) -> contracts.AccountRelationship | None:
    """End an active assignment. Returns None when no active assignment matches this account
    (missing, another account's, or already ended) — mapped to 404."""
    try:
        relationship = _relationships_logic.end_relationship(
            team_id=team_id,
            account_id=account_id,
            relationship_id=str(relationship_id),
            actor=actor,
        )
    except _relationships_logic.AccountRelationshipNotFound:
        return None
    return _to_account_relationship(relationship)


# --- EventStream ---


class EventStreamValidationError(Exception):
    """Raised when an event-stream write references a Slack integration that isn't the
    team's (→ 400)."""


class EventStreamConflictError(Exception):
    """Raised when a user creates a second event stream in a team (→ 409)."""


def _own_streams(team_id: int, user: "User"):
    """Streams are per-user: every read and write is scoped to the caller's own stream."""
    return EventStream.objects.for_team(team_id).filter(created_by=user)


def _to_event_stream_view(stream: EventStream) -> contracts.EventStreamView:
    account_ids = list(stream.members.order_by("created_at").values_list("account_id", flat=True))
    return contracts.EventStreamView(
        id=stream.id,
        enabled=stream.enabled,
        event_names=list(stream.event_names or []),
        slack_integration=stream.slack_integration_id,
        slack_channel_id=stream.slack_channel_id,
        slack_channel_name=stream.slack_channel_name,
        account_ids=account_ids,
        created_at=stream.created_at,
        created_by=stream.created_by_id,
        updated_at=stream.updated_at,
    )


def _validate_slack_integration(team_id: int, integration_id: int | None) -> None:
    if integration_id is None:
        return
    if not Integration.objects.filter(team_id=team_id, id=integration_id, kind="slack").exists():
        raise EventStreamValidationError("Slack integration not found for this team.")


def _normalize_event_names(event_names: Iterable[str]) -> list[str]:
    """Deduplicated, order-preserving event names with blanks dropped."""
    return [name for name in dict.fromkeys(event_names) if name and name.strip()]


def list_event_streams(team_id: int, *, user: "User") -> list[contracts.EventStreamView]:
    """The caller's event streams — at most one exists per user (unique per team+owner)."""
    return [_to_event_stream_view(s) for s in _own_streams(team_id, user).order_by("created_at")]


def create_event_stream(
    *,
    team_id: int,
    enabled: bool,
    event_names: list[str],
    slack_integration_id: int | None,
    slack_channel_id: str,
    slack_channel_name: str,
    user: "User",
) -> contracts.EventStreamView:
    """Create the caller's event stream. Raises :class:`EventStreamConflictError` when they
    already have one and :class:`EventStreamValidationError` for a foreign Slack integration."""
    _validate_slack_integration(team_id, slack_integration_id)
    try:
        stream = EventStream.objects.for_team(team_id).create(
            team_id=team_id,
            created_by=user,
            enabled=enabled,
            event_names=_normalize_event_names(event_names),
            slack_integration_id=slack_integration_id,
            slack_channel_id=slack_channel_id,
            slack_channel_name=slack_channel_name,
        )
    except IntegrityError as exc:
        if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
        raise EventStreamConflictError("You already have an event stream in this project.")
    return _to_event_stream_view(stream)


def update_event_stream(
    *, team_id: int, stream_id: str | UUID, fields: dict[str, Any], user: "User"
) -> contracts.EventStreamView | None:
    """Apply ``fields`` (enabled / event_names / slack_integration_id / slack_channel_id /
    slack_channel_name) to the caller's stream. Returns None (→ 404) when no stream matches."""
    stream = _own_streams(team_id, user).filter(id=stream_id).first()
    if stream is None:
        return None
    if "slack_integration_id" in fields:
        _validate_slack_integration(team_id, fields["slack_integration_id"])
    if "event_names" in fields:
        fields = {**fields, "event_names": _normalize_event_names(fields["event_names"])}
    for attr, value in fields.items():
        setattr(stream, attr, value)
    stream.save()
    return _to_event_stream_view(stream)


def delete_event_stream(*, team_id: int, stream_id: str | UUID, user: "User") -> bool:
    """Delete the caller's stream (memberships cascade) and archive its managed Slack
    destination so it can't keep delivering. Returns False when none matched (→ 404)."""
    stream = _own_streams(team_id, user).filter(id=stream_id).first()
    if stream is None:
        return False
    with transaction.atomic():
        archive_event_stream_destination(stream)
        stream.delete()
    return True


def delete_event_streams_for_user(*, user_id: int, organization_id: UUID | str) -> int:
    """Archive and delete every event stream the user owns across the organization's teams.
    Called by core when the user's organization membership is removed — a departed member's
    stream must stop delivering customer events to their Slack channel. Returns the number
    of streams deleted."""
    streams = list(EventStream.objects.unscoped().filter(created_by_id=user_id, team__organization_id=organization_id))
    for stream in streams:
        with transaction.atomic():
            archive_event_stream_destination(stream)
            stream.delete()
    return len(streams)


def _event_streams_containing_account(account: Account) -> list[EventStream]:
    return list(EventStream.objects.for_team(account.team_id).filter(members__account=account))


def set_event_stream_member(
    *,
    team_id: int,
    stream_id: str | UUID,
    account_id: str | UUID,
    included: bool,
    user: "User",
    user_access_control: "UserAccessControl",
) -> contracts.EventStreamView | None:
    """Add or remove an account from the caller's stream. Idempotent in both directions.
    Returns None (→ 404) when no stream matches; raises ``Account_DoesNotExist`` for a
    foreign, unknown, or (when adding) object-level-denied account."""
    stream = _own_streams(team_id, user).filter(id=stream_id).first()
    if stream is None:
        return None
    account = Account.objects.for_team(team_id).filter(id=account_id).first()
    if account is None:
        raise Account_DoesNotExist()
    if included:
        # Adding an account pipes its events into Slack, so a denied account must behave
        # like an unknown one. Removal stays team-scoped: members must be droppable even
        # after access to them is revoked.
        if get_accessible_account_id(team_id, str(account.id), user_access_control) is None:
            raise Account_DoesNotExist()
        # for_team() filters don't propagate into creation — team_id must be in defaults.
        EventStreamMember.objects.for_team(team_id).get_or_create(
            stream=stream,
            account=account,
            defaults={"team_id": team_id, "created_by": user},
        )
    else:
        EventStreamMember.objects.for_team(team_id).filter(stream=stream, account=account).delete()
    return _to_event_stream_view(stream)


# --- Announcements ---


def _to_announcement_delivery_view(delivery) -> contracts.AnnouncementDeliveryView:
    return contracts.AnnouncementDeliveryView(
        id=delivery.id,
        slack_channel_id=delivery.slack_channel_id,
        slack_channel_name=delivery.slack_channel_name,
        status=delivery.status,
        error=delivery.error,
        slack_message_ts=delivery.slack_message_ts,
        sent_at=delivery.sent_at,
    )


def _to_announcement_view(announcement) -> contracts.AnnouncementView:
    return contracts.AnnouncementView(
        id=announcement.id,
        short_id=announcement.short_id,
        message=announcement.message,
        status=announcement.status,
        total_channels=announcement.total_channels,
        sent_count=announcement.sent_count,
        failed_count=announcement.failed_count,
        sent_at=announcement.sent_at,
        created_at=announcement.created_at,
        created_by=_to_user_basic_info(announcement.created_by),
        deliveries=[_to_announcement_delivery_view(d) for d in announcement.deliveries.all()],
    )


def _announcements_queryset(team_id: int):
    return (
        Announcement.objects.for_team(team_id)
        .select_related("created_by")
        .prefetch_related("deliveries")
        .order_by("-created_at")
    )


def list_announcements(team_id: int, offset: int, limit: int) -> tuple[list[contracts.AnnouncementView], int]:
    queryset = _announcements_queryset(team_id)
    total_count = queryset.count()
    page = queryset[offset : offset + limit]
    return [_to_announcement_view(a) for a in page], total_count


def get_announcement(team_id: int, short_id: str) -> contracts.AnnouncementView | None:
    announcement = _announcements_queryset(team_id).filter(short_id=short_id).first()
    return _to_announcement_view(announcement) if announcement is not None else None


def create_announcement(*, team_id: int, user: "User", message: str, channels: list[str]) -> contracts.AnnouncementView:
    team = Team.objects.get(id=team_id)
    announcement = _announcements_logic.create_announcement(team, user, message, channels)
    # Dispatch only after the delivery rows commit; a rollback must not leave a phantom task.
    transaction.on_commit(lambda: send_announcement.delay(str(announcement.id), team_id))
    return _to_announcement_view(announcement)


def list_announcement_channels(team_id: int) -> list[contracts.AnnouncementChannelView]:
    try:
        return _announcements_logic.list_channels(team_id)
    except SupportSlackNotConfigured:
        return []
    except SupportSlackChannelsUnavailable:
        logger.warning("announcement_channels_unavailable", team_id=team_id)
        return []
