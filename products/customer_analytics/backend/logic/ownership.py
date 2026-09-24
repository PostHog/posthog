"""
Controlled relationships on accounts: which relationship definitions customer analytics may take
control of for a team, which accounts each is controlled on, the per-(account, definition) control
timestamp that fences automated claims, and the ownership block the external API exposes.
Per-account mutations reach this module from ``logic/relationships.py`` under the Account row lock.
Whether a definition is controlled at all changes only through ``set_controlled``, under the
definition lock.
"""

import json
import hashlib
from collections import defaultdict
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from django.db import transaction
from django.db.models import F, QuerySet
from django.db.models.functions import Greatest, Now
from django.utils import timezone

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.utils import get_instance_region

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import OwnershipRoleDiagnostic
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipControl,
    AccountRelationshipDefinition,
)

# An automated claim must be later than the fence by more than this, so a clock difference between
# the allocation source and this database cannot make a stale decision look fresh.
CLAIM_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


class InvalidControlChangeError(Exception):
    """The definition cannot take or give up control: wrong team, multi-holder, accounts still
    enrolled under it, or a claim view bound to it."""


def controlled_definitions(team_id: int) -> QuerySet[AccountRelationshipDefinition]:
    return AccountRelationshipDefinition.objects.for_team(team_id).filter(is_controlled=True).order_by("name")


def lock_definitions(team_id: int, definition_ids: Collection[str | UUID]) -> list[AccountRelationshipDefinition]:
    """The definitions, read under their row locks and taken in id order so two callers with
    overlapping sets never wait on each other; call inside ``transaction.atomic()``.

    Enrollment and control changes take this lock so ``is_controlled`` cannot flip between a check
    and the write that relied on it. ``no_key`` keeps it compatible with the ``FOR KEY SHARE`` lock a
    relationship insert takes on its definition, so a writer holding the account lock never waits on
    this one and the two cannot deadlock."""
    return list(
        AccountRelationshipDefinition.objects.for_team(team_id)
        .select_for_update(no_key=True)
        .filter(id__in=definition_ids)
        .order_by("id")
    )


def lock_definition(team_id: int, definition_id: str | UUID) -> AccountRelationshipDefinition | None:
    """One definition under its row lock, or None where the team has no such definition."""
    locked = lock_definitions(team_id, [definition_id])
    return locked[0] if locked else None


def set_controlled(team_id: int, definition_id: UUID, controlled: bool) -> AccountRelationshipDefinition:
    """Let customer analytics take control of the definition per account, or stop it.

    Taking control enrolls no account at once. From then on, a person's change to a controlled
    relationship on a linked account enrolls that account (see ``logic/relationships.py``). Reviewed
    adoption enrolls accounts in batches. Giving control up is refused while any account is
    enrolled, because those accounts would fall back to legacy authority at once. It is also refused
    while a claim view is bound to the definition, because a claim can only fill a controlled
    relationship.
    """
    with transaction.atomic():
        definition = lock_definition(team_id, definition_id)
        if definition is None:
            raise InvalidControlChangeError(f"No relationship definition {definition_id} in this project")
        if definition.is_controlled == controlled:
            return definition
        if controlled and not definition.is_single_holder:
            raise InvalidControlChangeError(
                f"{definition.name} allows several holders; a controlled relationship needs one"
            )
        if not controlled:
            enrolled = AccountRelationshipControl.objects.for_team(team_id).filter(definition=definition).count()
            if enrolled:
                raise InvalidControlChangeError(
                    f"{enrolled} account(s) are enrolled under {definition.name}; control cannot end while they are"
                )
            if definition.claim_saved_query_id is not None:
                raise InvalidControlChangeError(f"{definition.name} has a claim view bound; clear that binding first")
        definition.is_controlled = controlled
        definition.save(update_fields=["is_controlled", "updated_at"])
        return definition


def control_for(account: Account, definition: AccountRelationshipDefinition) -> AccountRelationshipControl | None:
    """The account's control row for the definition, or None while the relationship is unmanaged
    there. The row's presence is authoritative, not the caller's copy of ``is_controlled``, which was
    read before the account lock and may predate an enrollment that has since committed. Read it under
    the Account lock when the caller will act on it."""
    return (
        AccountRelationshipControl.objects.for_team(account.team_id)
        .filter(account=account, definition=definition)
        .first()
    )


def enroll(
    account: Account, definition: AccountRelationshipDefinition, created_by: User | None
) -> AccountRelationshipControl:
    """Create the control row, timed by the database clock like every later advance. Call under the
    definition and Account locks."""
    control = AccountRelationshipControl.objects.for_team(account.team_id).create(
        team_id=account.team_id,
        account=account,
        definition=definition,
        created_by=created_by,
        controlled_at=Now(),
    )
    control.refresh_from_db(fields=["controlled_at"])
    return control


def advance(control: AccountRelationshipControl) -> datetime:
    """Record a new decision on the controlled relationship and return its instant.

    Call while holding the Account row lock. The value comes from the database clock and is
    strictly later than the previous one, so two decisions in quick succession never share a fence
    and a claim can never be exactly equal to it.
    """
    queryset = AccountRelationshipControl.objects.for_team(control.team_id).filter(pk=control.pk)
    queryset.update(controlled_at=Greatest(Now(), F("controlled_at") + timedelta(microseconds=1)))
    control.controlled_at = queryset.values_list("controlled_at", flat=True).get()
    return control.controlled_at


def ownership_for_accounts(
    team_id: int, organization_id: UUID, accounts: Sequence[Account]
) -> dict[UUID, contracts.ExternalAccountOwnership]:
    """The ownership block for each account, read in one pass so a page of the external list costs
    a fixed number of queries."""
    definitions = list(controlled_definitions(team_id))
    controls: dict[tuple[UUID, UUID], AccountRelationshipControl] = {}
    active_by_account_and_definition: dict[tuple[UUID, UUID], list[AccountRelationship]] = defaultdict(list)
    if definitions and accounts:
        for control in AccountRelationshipControl.objects.for_team(team_id).filter(
            account__in=accounts, definition__in=definitions
        ):
            controls[(control.account_id, control.definition_id)] = control
        for relationship in (
            AccountRelationship.objects.for_team(team_id)
            .filter(account__in=accounts, definition__in=definitions, ended_at__isnull=True)
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
            roles=[
                _role_ownership(
                    definition,
                    controls.get((account.id, definition.id)),
                    active_by_account_and_definition.get((account.id, definition.id), []),
                    member_user_ids,
                )
                for definition in definitions
            ],
        )
        for account in accounts
    }


def ownership_for_account(account: Account) -> contracts.ExternalAccountOwnership:
    return ownership_for_accounts(account.team_id, account.team.organization_id, [account])[account.id]


def _role_ownership(
    definition: AccountRelationshipDefinition,
    control: AccountRelationshipControl | None,
    active: list[AccountRelationship],
    member_user_ids: set[int],
) -> contracts.ExternalAccountRoleOwnership:
    diagnostics: list[OwnershipRoleDiagnostic] = []
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
    if control is None:
        state = "unmanaged"
    elif diagnostics:
        state = "blocked"
    elif relationship is None:
        state = "cleared"
    else:
        state = "assigned"

    return contracts.ExternalAccountRoleOwnership(
        definition_id=definition.id,
        definition_name=definition.name,
        state=state,
        controlled_at=control.controlled_at if control is not None else None,
        relationship_id=relationship.id if relationship is not None else None,
        holder=holder,
        diagnostics=[cast(contracts.OwnershipRoleDiagnosticValue, str(diagnostic)) for diagnostic in diagnostics],
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


def allocation_rejection(allocated_at: datetime, fence: datetime | None) -> contracts.OwnershipClaimReason | None:
    """Why the allocation time cannot be trusted, or None when it can. It must be later than the fence
    by more than the clock-skew allowance and no further in the future than that same allowance;
    equal or uncertain ordering is rejected, because waiting cannot make the same decision newer."""
    if allocated_at > timezone.now() + CLAIM_CLOCK_SKEW_TOLERANCE:
        return "future_allocation"
    if fence is not None and allocated_at <= fence + CLAIM_CLOCK_SKEW_TOLERANCE:
        return "stale_allocation"
    return None
