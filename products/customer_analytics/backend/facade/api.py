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

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db.models import Q

from posthog.models.tagged_item import TaggedItem

from products.customer_analytics.backend.account_urls import build_account_deeplink as build_account_deeplink
from products.customer_analytics.backend.logic.usage_spike_notifications import (
    notify_managers_of_usage_spike as notify_managers_of_usage_spike,
)
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.models.account import AccountProperties as _ModelAccountProperties
from products.notebooks.backend.models import Notebook, ResourceNotebook

from . import contracts

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl


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
    links = (
        ResourceNotebook.objects.filter(
            account=account,
            notebook__deleted=False,
            notebook__visibility=Notebook.Visibility.INTERNAL,
        )
        .select_related("notebook")
        .order_by("-notebook__last_modified_at")
    )
    return [contracts.AccountNote(title=link.notebook.title, short_id=link.notebook.short_id) for link in links]


def get_account_context_data(
    team_id: int, account_id: str | None = None, external_id: str | None = None
) -> contracts.AccountContextData | None:
    """Fetch one account (by id or external_id, scoped to the team) with the tags
    and internal notes the assistant context renders.

    Returns None when no account matches or the identifier is malformed.
    """
    account = _resolve_account(team_id, account_id=account_id, external_id=external_id)
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
