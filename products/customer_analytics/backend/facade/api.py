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

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q

from celery import current_app
from pydantic import ValidationError as PydanticValidationError

from posthog.api.tagged_item import set_tags_on_object
from posthog.exceptions_capture import capture_exception
from posthog.models import OrganizationMembership, Tag
from posthog.models.activity_logging.activity_log import AuditableScope, Detail, changes_between, log_activity
from posthog.models.tag import tagify
from posthog.models.tagged_item import TaggedItem

from products.customer_analytics.backend.account_urls import build_account_deeplink as build_account_deeplink
from products.customer_analytics.backend.constants import ACCOUNT_ASSIGNMENT_ROLE_FIELDS
from products.customer_analytics.backend.logic import (
    custom_property_values as _custom_property_values_logic,
    relationships as _relationships_logic,
)
from products.customer_analytics.backend.logic.custom_property_definitions import (
    InvalidCustomPropertyOptions as InvalidCustomPropertyOptions,
    apply_option_side_effects,
    coerce_is_big_number,
    normalize_options,
)
from products.customer_analytics.backend.logic.usage_spike_notifications import (
    notify_managers_of_usage_spike as notify_managers_of_usage_spike,
)
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomerJourney,
    CustomerProfileConfig,
    CustomPropertyDefinition,
    CustomPropertySource,
    DisplayType,
)
from products.customer_analytics.backend.models.account import AccountProperties as _ModelAccountProperties
from products.notebooks.backend.facade import (
    api as notebooks,
    contracts as notebook_contracts,
)

# ResourceNotebook stays a direct import for the account-list Prefetch only — prefetching the
# account -> ResourceNotebook -> notebook relation can't cross a data facade. All account-notebook
# CRUD goes through `notebooks` (the facade). Tracked by the notebooks legacy-leak interface block.
from products.notebooks.backend.models import ResourceNotebook
from products.workflows.backend.services.template_input_usage import get_hog_flows_referencing_template_input_keys

from . import contracts

# The "Update account property" workflow action (Hog template) stores the custom property values it
# sets keyed by definition id under its ``properties`` input — the link we resolve into references.
_ACCOUNT_PROPERTY_TEMPLATE_ID = "template-posthog-update-account-property"
_ACCOUNT_PROPERTY_INPUT_KEY = "properties"

if TYPE_CHECKING:
    from posthog.models.user import User
    from posthog.rbac.user_access_control import UserAccessControl

    from products.customer_analytics.backend.models import CustomPropertyValue


def _to_assignment(assignment) -> contracts.AccountAssignment | None:
    if assignment is None:
        return None
    return contracts.AccountAssignment(id=assignment.id, email=assignment.email)


def _to_account_properties(properties: _ModelAccountProperties) -> contracts.AccountProperties:
    return contracts.AccountProperties(
        csm=_to_assignment(properties.csm),
        account_executive=_to_assignment(properties.account_executive),
        account_owner=_to_assignment(properties.account_owner),
        stripe_customer_id=properties.stripe_customer_id,
        hubspot_deal_id=properties.hubspot_deal_id,
        billing_id=properties.billing_id,
        sfdc_id=properties.sfdc_id,
        zendesk_id=properties.zendesk_id,
        slack_channel_id=properties.slack_channel_id,
        usage_dashboard_link=properties.usage_dashboard_link,
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
    team_id: int, query: str, user_access_control: "UserAccessControl", limit: int
) -> tuple[list[contracts.AccountRef], int]:
    """Accounts matching `query` by name or external id, access-filtered for the caller.

    Returns `(rows, total_count)` where `total_count` is the pre-limit match count.
    """
    queryset = _accounts_queryset(team_id, user_access_control).filter(
        Q(name__icontains=query) | Q(external_id__icontains=query)
    )
    total_count = queryset.count()
    rows = list(queryset.order_by("name")[:limit].values("id", "name", "external_id"))
    return [_to_account_ref(row) for row in rows], total_count


def list_accounts(
    team_id: int, offset: int, limit: int, user_access_control: "UserAccessControl"
) -> tuple[list[contracts.AccountRef], int]:
    """Accounts for the team, newest first, access-filtered for the caller.

    Returns `(rows, total_count)` where `total_count` is the full (unpaginated) count.
    """
    queryset = _accounts_queryset(team_id, user_access_control).order_by("-created_at")
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


# --- External (CDP worker) account API ---
#
# The data access, transactional write, org-membership resolution, tag
# application, and exception capture for the Bearer-authed external account
# endpoint. The view keeps only HTTP concerns (auth, throttles, the flag gate,
# request validation) and maps the results below to responses.


def _to_external_account(account: Account) -> contracts.ExternalAccount:
    """Map an account to the verbatim external wire shape.

    ``properties`` is the exact ``model_dump(mode="json")`` of the validated
    pydantic properties and ``tags`` the sorted tag names — byte-identical to
    what the CDP worker consumed before this moved behind the facade.
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
    return contracts.ExternalAccount(
        id=str(account.id),
        external_id=account.external_id,
        name=account.name,
        properties=account.properties.model_dump(mode="json"),
        tags=sorted(account.tagged_items.values_list("tag__name", flat=True)),
        relationships=relationships,
    )


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


def _apply_external_tags(account: Account, tags: list[str], mode: str) -> None:
    normalized = list({tagify(t) for t in tags})
    if mode == "remove":
        account.tagged_items.filter(tag__name__in=normalized).delete()
    elif mode == "set":
        set_tags_on_object(normalized, account)
    else:
        for tag_name in normalized:
            tag, _ = Tag.objects.get_or_create(name=tag_name, team_id=account.team_id)
            account.tagged_items.get_or_create(tag_id=tag.id)


def _apply_external_relationship_assignments(
    account: Account, assignments: dict[str, int | None]
) -> contracts.ExternalAccountUpdateResult | None:
    """Apply provided relationship assignments, keyed by definition name or UUID (None
    ends the active assignment). UUID keys are rename-safe — the new template uses them.
    Name keys stay valid for back-compat with the old template and external callers.
    Each non-None user id is resolved against an ``OrganizationMembership`` in the
    account's org so assignees are always trusted.
    Everything is validated before the first write — the caller's ``atomic()`` block
    returns (commits) on an error result rather than rolling back.
    """
    uuid_keys: dict[str, UUID] = {}
    for key in assignments:
        try:
            uuid_keys[key] = UUID(key)
        except ValueError:
            pass

    by_id: dict[UUID, AccountRelationshipDefinition] = {}
    by_name: dict[str, AccountRelationshipDefinition] = {}
    if assignments:
        # Every key doubles as a name candidate for back-compat with definitions literally
        # named like a UUID. UUID lookup wins, so a key matching one definition's id and
        # another definition's name resolves to the id match.
        for definition in AccountRelationshipDefinition.objects.for_team(account.team_id).filter(
            Q(id__in=uuid_keys.values()) | Q(name__in=assignments.keys())
        ):
            by_id[definition.id] = definition
            by_name[definition.name] = definition

    resolved: list[tuple[AccountRelationshipDefinition, User | None]] = []
    for key, user_id in assignments.items():
        definition = by_id.get(uuid_keys[key]) if key in uuid_keys else None
        definition = definition or by_name.get(key)
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
            _relationships_logic.end_active(team_id=account.team_id, account=account, definition=definition)
        else:
            _relationships_logic.assign(
                team_id=account.team_id, account=account, definition=definition, user=assignee, created_by=None
            )
    return None


def update_external_account(
    team_id: int,
    external_id: str,
    *,
    relationship_assignments: dict[str, int | None],
    tags: list[str] | None,
    tags_mode: str,
) -> contracts.ExternalAccountUpdateResult:
    """Apply relationship assignments and tags to an account, transactionally, for the
    external API.

    Assignments and tags are all-or-nothing — a tag failure must not leave the
    relationship changes committed. Returns a result the view maps to the exact HTTP
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
            error_result = _apply_external_relationship_assignments(account, relationship_assignments)
            if error_result is not None:
                return error_result
            if tags is not None:
                _apply_external_tags(account, tags, tags_mode)
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


class ResourceForbiddenError(Exception):
    """Raised when the caller passes resource/object access checks at the team level but
    lacks the object-level access required for the action — the view maps this to 403,
    matching the ``AccessControlPermission.has_object_permission`` path it replaces."""


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


def _set_tags(tags: list[str] | None, obj) -> None:
    """Replace ``obj``'s tags, creating/deleting ``TaggedItem`` rows individually so each
    change emits its own activity-log entry (the account activity stream depends on this).

    Mirrors ``posthog.api.tagged_item.set_tags_on_object`` + ``cleanup_orphan_tags`` but
    stays on pure-model imports so the facade keeps DRF off its import path. ``None`` means
    "tags not supplied" — leave them untouched (matches the serializer mixin).

    Sets ``obj.prefetched_tags`` to the resulting rows so a freshly-written account renders
    its new tags without re-reading a stale prefetch (the mixin did the same)."""
    if tags is None:
        return
    deduped_tags = list({tagify(t) for t in tags})
    tagged_item_objects = []
    for tag in deduped_tags:
        tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
        tagged_item_instance, _ = obj.tagged_items.get_or_create(tag_id=tag_instance.id)
        tagged_item_instance.tag = tag_instance
        tagged_item_objects.append(tagged_item_instance)
    for tagged_item in obj.tagged_items.exclude(tag__name__in=deduped_tags):
        tagged_item.delete()
    Tag.objects.filter(Q(team_id=obj.team_id) & Q(tagged_items__isnull=True)).delete()
    obj.prefetched_tags = tagged_item_objects


def _log_activity_swallowing(
    *,
    instance,
    scope: str,
    activity: str,
    name: str,
    organization_id,
    team_id: int,
    user: "User",
    was_impersonated: bool,
    previous=None,
) -> None:
    """Replicates ``posthog.api.utils.log_activity_from_viewset`` — including its blanket
    ``except: pass`` — for the account / customer-journey write paths."""
    try:
        detail_kwargs: dict[str, Any] = {"name": name}
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
) -> contracts.CustomPropertyDefinitionView:
    return contracts.CustomPropertyDefinitionView(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        display_type=definition.display_type,
        is_big_number=definition.is_big_number,
        created_at=definition.created_at,
        created_by=definition.created_by_id,
        updated_at=definition.updated_at,
        references=references or [],
        source=_definition_source_view(definition),
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


def _definition_source_view(definition: CustomPropertyDefinition) -> contracts.CustomPropertySourceView | None:
    """The source bound to this definition (reverse one-to-one ``source``), or None. List reads
    ``select_related("source")`` so this stays a cache hit; detail reads pay one extra query."""
    try:
        source = definition.source
    except CustomPropertySource.DoesNotExist:
        return None
    return _to_custom_property_source_view(source)


def list_custom_property_definitions(
    team_id: int, offset: int, limit: int, *, user_access_control: "UserAccessControl"
) -> tuple[list[contracts.CustomPropertyDefinitionView], int]:
    """Custom property definitions for the team, ordered by name. Returns ``(page, total_count)``.

    ``references`` (the workflows referencing each definition) is included only when the caller can
    read workflows — see ``_can_read_workflow_references``."""
    queryset = CustomPropertyDefinition.objects.filter(team_id=team_id).select_related("source").order_by("name")
    total_count = queryset.count()
    page = queryset[offset : offset + limit]
    references = (
        _custom_property_references_by_definition_id(team_id)
        if _can_read_workflow_references(user_access_control)
        else {}
    )
    return [_to_custom_property_definition_view(d, references.get(str(d.id), [])) for d in page], total_count


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
    return _to_custom_property_definition_view(definition, references)


def create_custom_property_definition(
    *,
    team_id: int,
    name: str,
    description: str | None,
    display_type: str,
    is_big_number: bool,
    options: list[dict[str, Any]] | None = None,
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


def update_custom_property_definition(
    *,
    team_id: int,
    definition_id: str,
    fields: dict[str, Any],
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.CustomPropertyDefinitionView | None:
    """Apply ``fields`` (only the keys the caller sent) to a team-scoped definition. Returns the
    updated view, or None when no definition matches the id for this team (→ 404)."""
    definition = _get_team_scoped(CustomPropertyDefinition, team_id, definition_id)
    if definition is None:
        return None
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
    return _to_custom_property_definition_view(definition)


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


def _to_custom_property_source_view(source: CustomPropertySource) -> contracts.CustomPropertySourceView:
    return contracts.CustomPropertySourceView(
        id=source.id,
        definition=source.definition_id,
        saved_query=source.saved_query_id,
        source_column=source.source_column,
        key_column=source.key_column,
        is_enabled=source.is_enabled,
        consecutive_failures=source.consecutive_failures,
        last_synced_at=source.last_synced_at,
        last_sync_error=source.last_sync_error,
        created_at=source.created_at,
        created_by=source.created_by_id,
        updated_at=source.updated_at,
    )


def _saved_query_belongs_to_team(team_id: int, saved_query_id) -> bool:
    """Whether the saved query exists for this team and isn't soft-deleted. Uses ``apps.get_model`` so
    customer_analytics never imports data_modeling (which isn't a dependency)."""
    saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
    return saved_query_model.objects.filter(id=saved_query_id, team_id=team_id).exclude(deleted=True).exists()


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


def list_custom_property_sources(
    team_id: int, offset: int, limit: int
) -> tuple[list[contracts.CustomPropertySourceView], int]:
    """Custom-property sources for the team, newest first. Returns ``(page, total_count)``."""
    queryset = CustomPropertySource.objects.for_team(team_id).order_by("-created_at")
    total_count = queryset.count()
    page = queryset[offset : offset + limit]
    return [_to_custom_property_source_view(s) for s in page], total_count


def get_custom_property_source(team_id: int, source_id: str) -> contracts.CustomPropertySourceView | None:
    source = CustomPropertySource.objects.for_team(team_id).filter(id=source_id).first()
    return _to_custom_property_source_view(source) if source is not None else None


def create_custom_property_source(
    *,
    team_id: int,
    definition_id: str | UUID,
    saved_query_id: str | UUID,
    source_column: str,
    key_column: str,
    is_enabled: bool,
    user: "User",
) -> contracts.CustomPropertySourceView:
    if not _saved_query_belongs_to_team(team_id, saved_query_id):
        raise CustomPropertySourceValidationError("Saved query not found for this team.")
    if _get_team_scoped(CustomPropertyDefinition, team_id, definition_id) is None:
        raise CustomPropertySourceValidationError("Custom property definition not found for this team.")
    try:
        source = CustomPropertySource.objects.for_team(team_id).create(
            team_id=team_id,
            created_by=user,
            definition_id=definition_id,
            saved_query_id=saved_query_id,
            source_column=source_column,
            key_column=key_column,
            is_enabled=is_enabled,
        )
    except IntegrityError as exc:
        # Both FKs are team-validated above, so the only expected violation is the definition's
        # one-to-one uniqueness; re-raise anything else instead of mislabeling it as a duplicate.
        if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
        raise CustomPropertySourceValidationError("This custom property already has a source.")
    _enqueue_sync_if_enabled(source)
    return _to_custom_property_source_view(source)


def update_custom_property_source(
    *, team_id: int, source_id: str, fields: dict[str, Any]
) -> contracts.CustomPropertySourceView | None:
    """Apply ``fields`` (source_column / key_column / is_enabled) to a team-scoped source. Re-enabling
    (is_enabled False→True) resets the failure streak and clears the last error. Returns None (→ 404)
    when no source matches."""
    source = CustomPropertySource.objects.for_team(team_id).filter(id=source_id).first()
    if source is None:
        return None
    reenabling = fields.get("is_enabled") is True and not source.is_enabled
    columns_changed = any(
        attr in fields and fields[attr] != getattr(source, attr) for attr in ("source_column", "key_column")
    )
    for attr, value in fields.items():
        setattr(source, attr, value)
    if reenabling:
        source.consecutive_failures = 0
        source.last_sync_error = None
    source.save()
    # Only re-sync on a change that affects what gets written — not on every (possibly no-op) PATCH.
    if reenabling or columns_changed:
        _enqueue_sync_if_enabled(source)
    return _to_custom_property_source_view(source)


def delete_custom_property_source(*, team_id: int, source_id: str) -> bool:
    """Delete a team-scoped source. Returns False when none matched (→ 404)."""
    deleted, _ = CustomPropertySource.objects.for_team(team_id).filter(id=source_id).delete()
    return deleted > 0


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
    from products.product_analytics.backend.models.insight import Insight

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
        # no assignments serializes ``properties`` as ``{}`` exactly as before.
        properties=account._properties or {},
        # Unsorted, matching the old ``TaggedItemSerializerMixin.to_representation`` output.
        tags=_account_view_tags(account),
        notebooks=_account_view_notebooks(account),
        created_at=account.created_at,
        created_by=account.created_by_id,
        updated_at=account.updated_at,
    )


def list_accounts_for_view(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    offset: int,
    limit: int,
    search: str | None = None,
    tags: list[str] | None = None,
    csm: str | None = None,
    account_executive: str | None = None,
    account_owner: str | None = None,
    all_roles_unassigned: bool = False,
    ordering: str | None = None,
) -> tuple[list[contracts.AccountView], int]:
    """The accounts list endpoint, behind the facade: team + object-level access filtering,
    the search / tags / role / ordering query filters, notebook + tag prefetching, and
    pagination. Returns ``(page, total_count)``. ``tags``/``ordering`` are pre-validated by
    the view; an empty ``tags`` list is treated as "no tag filter" (matches old behavior)."""
    queryset = _accounts_queryset(team_id, user_access_control).prefetch_related(
        Prefetch("notebooks", queryset=ResourceNotebook.objects.select_related("notebook")),
        Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
    )

    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(external_id__icontains=search))

    if tags:
        queryset = queryset.filter(tagged_items__tag__name__in=tags).distinct()

    # An unset role serializes as JSON null, which ``_properties__role__isnull`` does not
    # match; probing the nested ``id`` matches every unassigned shape (missing key, null
    # value, or empty object).
    if all_roles_unassigned:
        queryset = queryset.filter(
            _properties__csm__id__isnull=True,
            _properties__account_executive__id__isnull=True,
            _properties__account_owner__id__isnull=True,
        )

    if csm == "unassigned":
        queryset = queryset.filter(_properties__csm__id__isnull=True)
    elif csm:
        try:
            queryset = queryset.filter(_properties__csm__id=int(csm))
        except ValueError:
            # Malformed user id is a no-op (return all), not "match nothing" — old behavior.
            pass

    if account_executive == "unassigned":
        queryset = queryset.filter(_properties__account_executive__id__isnull=True)
    elif account_executive:
        try:
            queryset = queryset.filter(_properties__account_executive__id=int(account_executive))
        except ValueError:
            pass

    if account_owner == "unassigned":
        queryset = queryset.filter(_properties__account_owner__id__isnull=True)
    elif account_owner:
        try:
            queryset = queryset.filter(_properties__account_owner__id=int(account_owner))
        except ValueError:
            pass

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


def create_account_for_view(
    *,
    team_id: int,
    team,
    input: contracts.CreateAccountInput,
    organization_id,
    user: "User",
    was_impersonated: bool,
) -> contracts.AccountView:
    try:
        with transaction.atomic():
            account = Account.objects.create_account(
                team=team,
                created_by=user,
                name=input.name,
                external_id=input.external_id,
                properties=input.properties,
            )
            _set_tags(input.tags, account)
            if any(field in (account._properties or {}) for field in ACCOUNT_ASSIGNMENT_ROLE_FIELDS):
                _relationships_logic.sync_from_account_properties(account, created_by=user)
    except PydanticValidationError as exc:
        raise AccountPropertiesValidationError(_format_pydantic_errors(exc))
    except IntegrityError:
        raise AccountConflictError("An account with this external_id already exists for this team.")
    _log_activity_swallowing(
        instance=account,
        scope="Account",
        activity="created",
        name=account.name,
        organization_id=organization_id,
        team_id=team_id,
        user=user,
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

    try:
        with transaction.atomic():
            account = Account.objects.update_account(account, **update_kwargs)
            _set_tags(input.tags, account)
            if input.properties_provided:
                _relationships_logic.sync_from_account_properties(account, created_by=user)
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
    return _to_account_view(account)


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
    account.delete()


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
    notes authored by the given users, ``assigned_to_ids`` to notes on accounts whose CSM or
    account executive is one of the given users. Returns ``(page, total_count)``."""
    accounts = _accounts_queryset(team_id, user_access_control)
    if assigned_to_ids:
        # "Assigned to" means CSM or AE (account_owner excluded), matching the accounts list
        # HogQL runner's ASSIGNED_ROLE_KEYS.
        accounts = accounts.filter(
            Q(_properties__csm__id__in=assigned_to_ids) | Q(_properties__account_executive__id__in=assigned_to_ids)
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
    created_by_id: int | None = None,
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
        created_by_id=created_by_id,
    )
    return _to_custom_property_value(row)


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
    *, team_id: int, account_id: str | UUID, relationship_id: str | UUID
) -> contracts.AccountRelationship | None:
    """End an active assignment. Returns None when no active assignment matches this account
    (missing, another account's, or already ended) — mapped to 404."""
    try:
        relationship = _relationships_logic.end_relationship(
            team_id=team_id, account_id=account_id, relationship_id=str(relationship_id)
        )
    except _relationships_logic.AccountRelationshipNotFound:
        return None
    return _to_account_relationship(relationship)
