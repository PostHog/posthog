"""
Commercial role authority on accounts: which relationship definitions carry the account executive
(AE) and customer success manager (CSM) roles for a team, whether an account manages each role,
the per-role control timestamp that fences automated initial claims, and the ownership block the
external API exposes. Mutations reach this module from ``logic/relationships.py`` while holding the
Account row lock.
"""

import json
import hashlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import F, Max
from django.db.models.functions import Greatest, Now
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.utils import get_instance_region

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import OwnershipRoleDiagnostic
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    TeamCustomerAnalyticsConfig,
)

OwnershipRole = Literal["ae", "csm"]
OWNERSHIP_ROLES: tuple[OwnershipRole, ...] = ("ae", "csm")

_CONTROLLED_AT_FIELD: dict[OwnershipRole, str] = {
    "ae": "ae_ownership_controlled_at",
    "csm": "csm_ownership_controlled_at",
}
_DEFINITION_FIELD: dict[OwnershipRole, str] = {
    "ae": "ae_relationship_definition_id",
    "csm": "csm_relationship_definition_id",
}


@frozen
class RoleBindings:
    """The relationship definition each commercial role is bound to for a team; None while unbound."""

    ae_definition_id: UUID | None = None
    csm_definition_id: UUID | None = None

    def role_of(self, definition_id: UUID) -> OwnershipRole | None:
        for role in OWNERSHIP_ROLES:
            if self.definition_id_of(role) == definition_id:
                return role
        return None

    def definition_id_of(self, role: OwnershipRole) -> UUID | None:
        return {"ae": self.ae_definition_id, "csm": self.csm_definition_id}[role]


def role_bindings(team_id: int) -> RoleBindings:
    row = (
        TeamCustomerAnalyticsConfig.objects.filter(team_id=team_id)
        .values_list(_DEFINITION_FIELD["ae"], _DEFINITION_FIELD["csm"])
        .first()
    )
    if row is None:
        return RoleBindings()
    return RoleBindings(ae_definition_id=row[0], csm_definition_id=row[1])


class InvalidRoleBindingError(Exception):
    """The definition cannot carry a commercial role: wrong team, multi-holder, or already bound to
    the other role."""


def lock_role_bindings(team_id: int) -> RoleBindings:
    """The bindings, read under the config row lock; call inside ``transaction.atomic()``.

    Enrollment takes this lock so a binding change cannot slip in between its managed-account
    check and the moment an account becomes managed under the old definition."""
    row = (
        TeamCustomerAnalyticsConfig.objects.select_for_update()
        .filter(team_id=team_id)
        .values_list(_DEFINITION_FIELD["ae"], _DEFINITION_FIELD["csm"])
        .first()
    )
    if row is None:
        return RoleBindings()
    return RoleBindings(ae_definition_id=row[0], csm_definition_id=row[1])


def bind_role(team: Team, role: OwnershipRole, definition_id: UUID | None) -> RoleBindings:
    """Bind the role to a definition of this team, or unbind it with None, and return the bindings.

    While any account manages the role, the binding is frozen: changing it would leave the managed
    accounts' fences pointing at history under the old definition and would let that definition,
    and every accepted claim under it, be deleted. The config row lock serializes this against
    enrollment and against a concurrent binding of the other role.
    """
    get_or_create_team_extension(team, TeamCustomerAnalyticsConfig)
    with transaction.atomic():
        config = TeamCustomerAnalyticsConfig.objects.select_for_update().get(team_id=team.id)
        return _bind_role_locked(config, role, definition_id)


def _bind_role_locked(
    config: TeamCustomerAnalyticsConfig, role: OwnershipRole, definition_id: UUID | None
) -> RoleBindings:
    team_id = config.team_id
    current_definition_id = getattr(config, _DEFINITION_FIELD[role])
    if current_definition_id != definition_id and current_definition_id is not None:
        managed_count = (
            Account.objects.for_team(team_id).filter(**{f"{_CONTROLLED_AT_FIELD[role]}__isnull": False}).count()
        )
        if managed_count:
            raise InvalidRoleBindingError(
                f"{managed_count} account(s) manage the {role.upper()} role; the binding cannot change while they do"
            )
    if definition_id is not None:
        definition = AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).first()
        if definition is None:
            raise InvalidRoleBindingError(f"No relationship definition {definition_id} in this project")
        if not definition.is_single_holder:
            raise InvalidRoleBindingError(f"{definition.name} allows several holders; a commercial role needs one")
        other_role = next(other for other in OWNERSHIP_ROLES if other != role)
        if getattr(config, _DEFINITION_FIELD[other_role]) == definition_id:
            raise InvalidRoleBindingError(f"{definition.name} is already bound to the {other_role.upper()} role")
    setattr(config, _DEFINITION_FIELD[role], definition_id)
    config.save(update_fields=[_DEFINITION_FIELD[role].removesuffix("_id")])
    return role_bindings(team_id)


def controlled_at(account: Account, role: OwnershipRole) -> datetime | None:
    return getattr(account, _CONTROLLED_AT_FIELD[role])


def is_managed(account: Account, role: OwnershipRole) -> bool:
    return controlled_at(account, role) is not None


def advance_control_timestamp(account: Account, role: OwnershipRole) -> datetime:
    """Record a new authoritative decision for the role and return its instant.

    Call while holding the Account row lock. The value comes from the database clock and is
    strictly later than the previous one, so two decisions in quick succession never share a fence
    and a claim can never be exactly equal to it.
    """
    field = _CONTROLLED_AT_FIELD[role]
    queryset = Account.objects.for_team(account.team_id).filter(pk=account.pk)
    queryset.update(**{field: Greatest(Now(), F(field) + timedelta(microseconds=1))})
    advanced_to = queryset.values_list(field, flat=True).get()
    setattr(account, field, advanced_to)
    return advanced_to


def ownership_for_accounts(
    team_id: int, organization_id: UUID, accounts: Sequence[Account]
) -> dict[UUID, contracts.ExternalAccountOwnership]:
    """The ownership block for each account, read in one pass so a page of the external list costs
    a fixed number of queries."""
    bindings = role_bindings(team_id)
    bound_definition_ids = [
        definition_id for definition_id in (bindings.ae_definition_id, bindings.csm_definition_id) if definition_id
    ]
    active_by_account_and_definition: dict[tuple[UUID, UUID], list[AccountRelationship]] = defaultdict(list)
    if bound_definition_ids and accounts:
        for relationship in (
            AccountRelationship.objects.for_team(team_id)
            .filter(account__in=accounts, definition_id__in=bound_definition_ids, ended_at__isnull=True)
            .select_related("user")
            .order_by("started_at")
        ):
            active_by_account_and_definition[(relationship.account_id, relationship.definition_id)].append(relationship)
    holder_user_ids = {
        relationship.user_id
        for rows in active_by_account_and_definition.values()
        for relationship in rows
        if relationship.user_id is not None
    }
    member_user_ids = set(
        OrganizationMembership.objects.filter(organization_id=organization_id, user_id__in=holder_user_ids).values_list(
            "user_id", flat=True
        )
    )
    region = get_instance_region()
    return {
        account.id: contracts.ExternalAccountOwnership(
            account_id=str(account.id),
            external_id=account.external_id,
            region=region.lower() if region else None,
            ae=_role_ownership(account, "ae", bindings, active_by_account_and_definition, member_user_ids),
            csm=_role_ownership(account, "csm", bindings, active_by_account_and_definition, member_user_ids),
        )
        for account in accounts
    }


def ownership_for_account(account: Account) -> contracts.ExternalAccountOwnership:
    return ownership_for_accounts(account.team_id, account.team.organization_id, [account])[account.id]


def _role_ownership(
    account: Account,
    role: OwnershipRole,
    bindings: RoleBindings,
    active_by_account_and_definition: dict[tuple[UUID, UUID], list[AccountRelationship]],
    member_user_ids: set[int],
) -> contracts.ExternalAccountRoleOwnership:
    definition_id = bindings.definition_id_of(role)
    fence = controlled_at(account, role)
    active = active_by_account_and_definition.get((account.id, definition_id), []) if definition_id else []
    diagnostics: list[str] = []
    if definition_id is None:
        diagnostics.append(OwnershipRoleDiagnostic.ROLE_UNBOUND)
    if len(active) > 1:
        diagnostics.append(OwnershipRoleDiagnostic.MULTIPLE_ACTIVE_HOLDERS)

    relationship = active[0] if active else None
    holder = None
    if relationship is not None:
        user = relationship.user
        if user is None:
            diagnostics.append(OwnershipRoleDiagnostic.HOLDER_MISSING)
        else:
            is_member = user.id in member_user_ids
            if not user.is_active:
                diagnostics.append(OwnershipRoleDiagnostic.HOLDER_INACTIVE)
            if not is_member:
                diagnostics.append(OwnershipRoleDiagnostic.HOLDER_NOT_IN_ORGANIZATION)
            # The single-account route also answers to the team token, so a holder outside the
            # organization is identified by id only, as the `relationships` field already does.
            holder = contracts.ExternalAccountOwnershipHolder(
                user_id=user.id,
                email=user.email if is_member else None,
                name=(f"{user.first_name} {user.last_name}".strip() or None) if is_member else None,
                is_organization_member=is_member,
                is_active=user.is_active,
            )

    state: contracts.OwnershipRoleStateValue
    if fence is None:
        state = "unmanaged"
    elif diagnostics:
        state = "blocked"
    elif relationship is None:
        state = "cleared"
    else:
        state = "assigned"

    return contracts.ExternalAccountRoleOwnership(
        state=state,
        definition_id=definition_id,
        controlled_at=fence,
        relationship_id=relationship.id if relationship is not None else None,
        holder=holder,
        diagnostics=[str(diagnostic) for diagnostic in diagnostics],
    )


def canonical_digest(payload: dict) -> str:
    """SHA-256 of a payload serialized key-order-independently, so the same facts always digest the
    same. Every value must be JSON-serializable."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def region_matches(region: str) -> bool:
    """A self-hosted or test instance has no region to check against; cloud instances require the
    decision to name theirs."""
    instance_region = get_instance_region()
    return instance_region is None or region == instance_region.lower()


def claim_clock_skew_tolerance(team: Team) -> timedelta:
    config = get_or_create_team_extension(team, TeamCustomerAnalyticsConfig)
    return timedelta(seconds=config.ownership_claim_clock_skew_tolerance_seconds)


def role_fence(account: Account, role: OwnershipRole, definition: AccountRelationshipDefinition) -> datetime | None:
    """The latest instant at which the role was decided: its control timestamp or any retained
    relationship transition under the bound definition, whichever is later."""
    transitions = (
        AccountRelationship.objects.for_team(account.team_id)
        .filter(account=account, definition=definition)
        .aggregate(started=Max("started_at"), ended=Max("ended_at"))
    )
    candidates = [
        value for value in (controlled_at(account, role), transitions["started"], transitions["ended"]) if value
    ]
    return max(candidates) if candidates else None


def allocation_rejection(
    allocated_at: datetime, fence: datetime | None, *, tolerance: timedelta
) -> contracts.OwnershipClaimReason | None:
    """Why the allocation time cannot be trusted, or None when it can. It must be later than the fence
    by more than the clock-skew allowance and no further in the future than that same allowance;
    equal or uncertain ordering is rejected, because waiting cannot make the same decision newer."""
    if allocated_at > timezone.now() + tolerance:
        return "future_allocation"
    if fence is not None and allocated_at <= fence + tolerance:
        return "stale_allocation"
    return None
