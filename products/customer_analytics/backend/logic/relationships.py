"""
Assign/end transactions for account relationships: the one write path for every relationship
writer (UI API, external API, AI tool, workflows, management commands). Each mutation locks the
Account row, applies the commercial-role policy, advances the role's control timestamp when the
account manages that role, and writes its activity row inside the same transaction, so a mutation
without an audit record cannot commit.
"""

import dataclasses
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import post_save
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityContextBase, ActivityLog, Change, Detail, log_activity
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.customer_analytics.backend.events import emit_account_relationship_changed
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import ownership
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition

ACTIVITY_SCOPE = "Account"


class AccountRelationshipNotFound(Exception):
    pass


class ManagedRolePolicyError(Exception):
    """An autonomous writer tried to change a commercial role that customer analytics manages."""


class ProtectedRelationshipHistoryError(Exception):
    """A commercial relationship row cannot be hard-deleted; end it instead."""


class RelationshipOccupiedError(Exception):
    """The single-holder relationship already has a different active holder and the caller asked
    not to replace one."""


@frozen
class Actor:
    """Who performs a relationship mutation and through which kind of writer."""

    source: AccountRelationshipSource
    user: User | None = None
    workflow_id: str | None = None

    @classmethod
    def human(cls, user: User | None = None) -> "Actor":
        return cls(source=AccountRelationshipSource.HUMAN, user=user)


# Writers with no person deciding. They may fill or change a role the account does not manage,
# never a managed one: transfers and clears of managed roles are human acts. Reviewed adoption
# reaches a managed role only through ``enroll_role``, which is the act of taking it over.
_AUTONOMOUS_SOURCES = frozenset(
    {
        AccountRelationshipSource.WORKFLOW,
        AccountRelationshipSource.AI,
        AccountRelationshipSource.SALESFORCE_CLAIM,
        AccountRelationshipSource.MIGRATION,
    }
)


@dataclasses.dataclass(frozen=True)
class AccountRelationshipActivityContext(ActivityContextBase):
    """Provenance stored beside the change so a reader can tell which writer acted, through which
    reference, and where the role fence stood afterwards."""

    relationship_id: str | None
    definition_id: str
    definition_name: str
    role: ownership.OwnershipRole | None
    source: str
    source_ref: str | None
    workflow_id: str | None
    previous_user_id: int | None
    current_user_id: int | None
    controlled_at: str | None
    # For a Salesforce decision: who decided at the source and when, as the Task recorded it.
    source_actor_id: str | None = None
    source_decided_at: str | None = None


def assign(
    *,
    team_id: int,
    account: Account,
    definition: AccountRelationshipDefinition,
    user: User,
    actor: Actor,
    emit_event: bool = True,
    replace_active: bool = True,
) -> AccountRelationship:
    """Assign the user. A single-holder definition hands off from the previous holder in the same
    transaction unless ``replace_active`` is False, in which case an occupied role raises. Assigning
    the current holder again is a no-op that records nothing, unless a person confirms a holder a
    Salesforce claim put there: that is a decision, so the claim row ends and a human row takes its
    place, and a later release of that Task finds nothing of its own to clear."""
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account.id)
        role = ownership.role_bindings(team_id).role_of(definition.id)
        _enforce_managed_role_policy(locked_account, role, actor)
        active = list(_active_relationships(team_id, locked_account, definition))
        existing = next((rel for rel in active if rel.user_id == user.id), None)
        human_confirms_claim = (
            existing is not None
            and actor.source == AccountRelationshipSource.HUMAN
            and existing.source == AccountRelationshipSource.SALESFORCE_CLAIM
        )
        if existing is not None and not human_confirms_claim:
            return existing
        if active and definition.is_single_holder and not replace_active:
            raise RelationshipOccupiedError(str(definition.id))

        previous_user = active[0].user if definition.is_single_holder and active else None
        if definition.is_single_holder:
            _end_rows(team_id, active, actor)
        relationship = AccountRelationship.objects.for_team(team_id).create(
            team_id=team_id,
            account=locked_account,
            definition=definition,
            user=user,
            created_by=actor.user,
            source=actor.source,
        )
        controlled_at = _advance_if_managed(locked_account, role)
        _record_transition(
            account=locked_account,
            actor=actor,
            activity="relationship_assigned",
            definition=definition,
            role=role,
            relationship=relationship,
            previous_user=previous_user,
            current_user=user,
            controlled_at=controlled_at,
            emit_event=emit_event,
        )
        return relationship


def end_active(
    *,
    team_id: int,
    account: Account,
    definition: AccountRelationshipDefinition,
    actor: Actor,
    emit_event: bool = True,
) -> int:
    """End every active assignment of the definition on the account and return how many ended.

    On a managed role, clearing an already-empty role is still a decision: the fence advances and
    the confirmation is recorded, so a later automated claim cannot treat the role as never reviewed.
    """
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account.id)
        role = ownership.role_bindings(team_id).role_of(definition.id)
        _enforce_managed_role_policy(locked_account, role, actor)
        active = list(_active_relationships(team_id, locked_account, definition))
        if not active and _managed_role(locked_account, role) is None:
            return 0

        _end_rows(team_id, active, actor)
        controlled_at = _advance_if_managed(locked_account, role)
        if not active:
            _record_transition(
                account=locked_account,
                actor=actor,
                activity="role_confirmed_empty",
                definition=definition,
                role=role,
                relationship=None,
                previous_user=None,
                current_user=None,
                controlled_at=controlled_at,
                emit_event=False,
            )
            return 0
        for relationship in active:
            _record_transition(
                account=locked_account,
                actor=actor,
                activity="relationship_ended",
                definition=definition,
                role=role,
                relationship=relationship,
                previous_user=relationship.user,
                current_user=None,
                controlled_at=controlled_at,
                emit_event=emit_event,
            )
        return len(active)


def end_relationship(
    *,
    team_id: int,
    account_id: str | UUID,
    relationship_id: str,
    actor: Actor,
    emit_event: bool = True,
) -> AccountRelationship:
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account_id, missing_id=relationship_id)
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("definition", "user")
            .filter(id=relationship_id, account=locked_account, ended_at__isnull=True)
            .first()
        )
        if relationship is None:
            raise AccountRelationshipNotFound(relationship_id)
        relationship.account = locked_account
        role = ownership.role_bindings(team_id).role_of(relationship.definition_id)
        _enforce_managed_role_policy(locked_account, role, actor)

        _end_rows(team_id, [relationship], actor)
        controlled_at = _advance_if_managed(locked_account, role)
        _record_transition(
            account=locked_account,
            actor=actor,
            activity="relationship_ended",
            definition=relationship.definition,
            role=role,
            relationship=relationship,
            previous_user=relationship.user,
            current_user=None,
            controlled_at=controlled_at,
            emit_event=emit_event,
        )
    return relationship


def delete_relationship(
    *,
    team_id: int,
    account_id: str | UUID,
    relationship_id: str,
    actor: Actor,
) -> None:
    """Hard-delete one relationship row, active or ended. Rows under a definition bound to a
    commercial role are history other systems replay against and are refused."""
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account_id, missing_id=relationship_id)
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("definition", "user")
            .filter(id=relationship_id, account=locked_account)
            .first()
        )
        if relationship is None:
            raise AccountRelationshipNotFound(relationship_id)
        role = ownership.role_bindings(team_id).role_of(relationship.definition_id)
        if role is not None:
            raise ProtectedRelationshipHistoryError(relationship_id)

        was_active = relationship.ended_at is None
        deleted_id = str(relationship.id)
        relationship.delete()
        _record_transition(
            account=locked_account,
            actor=actor,
            activity="relationship_deleted",
            definition=relationship.definition,
            role=None,
            relationship=None,
            relationship_id=deleted_id,
            previous_user=relationship.user,
            current_user=None,
            controlled_at=None,
            emit_event=was_active,
        )


class RoleUnboundError(Exception):
    """The team has not bound a relationship definition to this commercial role."""


def enroll_role(*, team_id: int, account: Account, role: ownership.OwnershipRole, actor: Actor) -> datetime:
    """Take authority over the role on this account and return its control timestamp.

    The current holder, if any, is kept: enrollment records that the role's state has been
    reviewed, so enrolling an empty role confirms it empty. Enrolling a managed role again is a
    no-op that keeps the existing fence.
    """
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account.id)
        definition_id = ownership.lock_role_bindings(team_id).definition_id_of(role)
        definition = (
            AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).first()
            if definition_id
            else None
        )
        if definition is None:
            raise RoleUnboundError(role)
        current_fence = ownership.controlled_at(locked_account, role)
        if current_fence is not None:
            return current_fence
        active = list(_active_relationships(team_id, locked_account, definition))
        holder = active[0] if active else None
        holder_user = holder.user if holder is not None else None
        controlled_at = ownership.advance_control_timestamp(locked_account, role)
        _record_transition(
            account=locked_account,
            actor=actor,
            activity="role_enrolled",
            definition=definition,
            role=role,
            relationship=holder,
            previous_user=holder_user,
            current_user=holder_user,
            controlled_at=controlled_at,
            emit_event=False,
        )
        return controlled_at


def claim_initial_ae(*, team: Team, decision: contracts.OwnershipClaimDecision) -> contracts.OwnershipClaimResult:
    """Apply an initial AE allocation frozen on a Salesforce Task.

    Under the Account lock, an accepted claim for the same Task is recognized first, so a Task read
    again on a later run is answered with the original decision even after the role has changed
    hands. A new Task may fill the AE role only when the account manages it, the role is empty, the
    assignee is a member, and the allocation is later than the role fence by more than the team's
    clock-skew allowance. Every refusal is returned as an outcome for the reconciler to record.
    """
    actor = Actor(source=AccountRelationshipSource.SALESFORCE_CLAIM)
    tolerance = ownership.claim_clock_skew_tolerance(team)
    with transaction.atomic():
        locked_account = _lock_account_by_external_id(team.id, decision.organization_id)
        if locked_account is None:
            return _claim_result("blocked", "account_not_found")
        accepted = _accepted_claim(team.id, decision.source_ref)
        if accepted is not None:
            if accepted.account_id != locked_account.id:
                return _claim_result("blocked", "identity_mismatch", accepted)
            return _claim_result("already_applied", None, accepted)

        definition = _bound_definition(team.id, "ae")
        if definition is None:
            return _claim_result("blocked", "role_unbound")
        if not ownership.is_managed(locked_account, "ae"):
            return _claim_result("blocked", "role_not_managed")
        if not ownership.region_matches(decision.region):
            return _claim_result("blocked", "identity_mismatch")
        membership = (
            OrganizationMembership.objects.select_related("user")
            .filter(organization_id=team.organization_id, user_id=decision.assignee_user_id, user__is_active=True)
            .first()
        )
        if membership is None:
            return _claim_result("blocked", "assignee_not_member")

        active = list(_active_relationships(team.id, locked_account, definition))
        if active:
            return _claim_result("rejected", "role_occupied", active[0])
        fence = ownership.role_fence(locked_account, "ae", definition)
        rejection = ownership.allocation_rejection(decision.allocated_at, fence, tolerance=tolerance)
        if rejection is not None:
            return _claim_result("rejected", rejection)

        relationship = AccountRelationship.objects.for_team(team.id).create(
            team_id=team.id,
            account=locked_account,
            definition=definition,
            user=membership.user,
            source=actor.source,
            source_ref=decision.source_ref,
        )
        controlled_at = ownership.advance_control_timestamp(locked_account, "ae")
        _record_transition(
            account=locked_account,
            actor=actor,
            activity="role_claimed",
            definition=definition,
            role="ae",
            relationship=relationship,
            previous_user=None,
            current_user=membership.user,
            controlled_at=controlled_at,
            source_actor_id=decision.source_assignee_id,
            source_decided_at=decision.allocated_at,
            emit_event=True,
        )
        return _claim_result("accepted", None, relationship, controlled_at)


def release_initial_ae(*, team: Team, decision: contracts.OwnershipClaimDecision) -> contracts.OwnershipClaimResult:
    """End the AE relationship that this Task's accepted claim created, and nothing else.

    A release needs no time fence: identity to the Task's own claim is the guard, so it cannot clear
    an AE assigned by a person or by another Task. Once a person has transferred, cleared or
    confirmed the role, the Task no longer holds it and the release is a no-op.
    """
    actor = Actor(source=AccountRelationshipSource.SALESFORCE_CLAIM)
    claim = _accepted_claim(team.id, decision.source_ref)
    if claim is None:
        return _claim_result("not_held", None)
    with transaction.atomic():
        # The claim names the account to lock, and is then read again under that lock: a person may
        # have ended it in between, which is exactly what makes the release a no-op.
        locked_account = _lock_or_raise(team.id, claim.account_id)
        accepted = _accepted_claim(team.id, decision.source_ref)
        if accepted is None:
            return _claim_result("not_held", None)
        if accepted.ended_at is not None:
            if accepted.ended_source == AccountRelationshipSource.SALESFORCE_CLAIM:
                return _claim_result("already_applied", None, accepted)
            return _claim_result("not_held", None, accepted)

        _end_rows(team.id, [accepted], actor)
        controlled_at = _advance_if_managed(locked_account, "ae")
        _record_transition(
            account=locked_account,
            actor=actor,
            activity="role_released",
            definition=accepted.definition,
            role="ae",
            relationship=accepted,
            previous_user=accepted.user,
            current_user=None,
            controlled_at=controlled_at,
            source_actor_id=decision.source_releaser_id,
            source_decided_at=decision.released_at,
            emit_event=True,
        )
        return _claim_result("cleared", None, accepted, controlled_at)


def _accepted_claim(team_id: int, source_ref: str) -> AccountRelationship | None:
    return (
        AccountRelationship.objects.for_team(team_id)
        .select_related("definition", "user")
        .filter(source=AccountRelationshipSource.SALESFORCE_CLAIM, source_ref=source_ref)
        .first()
    )


def _lock_account_by_external_id(team_id: int, external_id: str) -> Account | None:
    """Lock the account linked to the organization. The link is read again under the lock, because
    an account update between the lookup and the lock could have moved it to another organization."""
    account_id = (
        Account.objects.for_team(team_id).filter(external_id__iexact=external_id).values_list("id", flat=True).first()
    )
    locked = lock_account(team_id, account_id) if account_id is not None else None
    if locked is None or (locked.external_id or "").lower() != external_id.lower():
        return None
    return locked


def _bound_definition(team_id: int, role: ownership.OwnershipRole) -> AccountRelationshipDefinition | None:
    """The definition carrying the role for this team, or None while the role is unbound."""
    definition_id = ownership.role_bindings(team_id).definition_id_of(role)
    if definition_id is None:
        return None
    return AccountRelationshipDefinition.objects.for_team(team_id).filter(id=definition_id).first()


def _claim_result(
    outcome: contracts.OwnershipClaimOutcome,
    reason: contracts.OwnershipClaimReason | None,
    relationship: AccountRelationship | None = None,
    controlled_at: datetime | None = None,
) -> contracts.OwnershipClaimResult:
    return contracts.OwnershipClaimResult(
        outcome=outcome,
        reason=reason,
        relationship_id=relationship.id if relationship is not None else None,
        controlled_at=controlled_at,
    )


def _end_rows(team_id: int, rows: list[AccountRelationship], actor: Actor) -> None:
    """End the rows now and stamp which kind of writer ended them; the instances are updated in place."""
    if not rows:
        return
    ended_at = timezone.now()
    AccountRelationship.objects.for_team(team_id).filter(id__in=[row.id for row in rows]).update(
        ended_at=ended_at, ended_source=actor.source
    )
    for row in rows:
        row.ended_at = ended_at
        row.ended_source = actor.source


def lock_account(team_id: int, account_id: str | UUID) -> Account | None:
    """Serialize every relationship mutation on the account; call inside ``transaction.atomic()``.
    Locks only the account row: the joined team row is read, not locked, so a hot parent row is
    never held."""
    return (
        Account.objects.for_team(team_id)
        .select_related("team")
        .select_for_update(of=("self",))
        .filter(id=account_id)
        .first()
    )


def _lock_or_raise(team_id: int, account_id: str | UUID, *, missing_id: str | None = None) -> Account:
    """Lock the account for the caller's transaction, or report what the caller was asked about as
    not found: the account itself, or ``missing_id`` where the caller named a relationship."""
    account = lock_account(team_id, account_id)
    if account is None:
        raise AccountRelationshipNotFound(missing_id or str(account_id))
    return account


def _active_relationships(
    team_id: int, account: Account, definition: AccountRelationshipDefinition
) -> QuerySet[AccountRelationship]:
    return (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition=definition, ended_at__isnull=True)
        .select_related("user")
        .order_by("started_at")
    )


def _managed_role(account: Account, role: ownership.OwnershipRole | None) -> ownership.OwnershipRole | None:
    """The role the write touches, when it is a commercial role this account manages."""
    return role if role is not None and ownership.is_managed(account, role) else None


def _enforce_managed_role_policy(account: Account, role: ownership.OwnershipRole | None, actor: Actor) -> None:
    managed = _managed_role(account, role)
    if managed is not None and actor.source in _AUTONOMOUS_SOURCES:
        raise ManagedRolePolicyError(
            f"A {actor.source} writer cannot change the {managed.upper()} role on an account where it is managed"
        )


def _advance_if_managed(account: Account, role: ownership.OwnershipRole | None) -> datetime | None:
    managed = _managed_role(account, role)
    if managed is None:
        return None
    return ownership.advance_control_timestamp(account, managed)


def _record_transition(
    *,
    account: Account,
    actor: Actor,
    activity: str,
    definition: AccountRelationshipDefinition,
    role: ownership.OwnershipRole | None,
    relationship: AccountRelationship | None,
    previous_user: User | None,
    current_user: User | None,
    controlled_at: datetime | None,
    emit_event: bool,
    relationship_id: str | None = None,
    source_actor_id: str | None = None,
    source_decided_at: datetime | None = None,
) -> None:
    """Audit the change and, with ``emit_event``, announce it to consumers once the caller commits.

    The audit row is written now, inside the caller's transaction. ``log_activity`` on its own would
    defer the insert to after commit and drop it on failure, which would let a role change commit
    without a record of who made it.
    """
    context = AccountRelationshipActivityContext(
        relationship_id=str(relationship.id) if relationship is not None else relationship_id,
        definition_id=str(definition.id),
        definition_name=definition.name,
        role=role,
        source=str(actor.source),
        source_ref=relationship.source_ref if relationship is not None else None,
        workflow_id=actor.workflow_id,
        previous_user_id=previous_user.id if previous_user is not None else None,
        current_user_id=current_user.id if current_user is not None else None,
        controlled_at=controlled_at.isoformat() if controlled_at is not None else None,
        source_actor_id=source_actor_id,
        source_decided_at=source_decided_at.isoformat() if source_decided_at is not None else None,
    )
    entry = log_activity(
        organization_id=account.team.organization_id,
        team_id=account.team_id,
        user=actor.user,
        was_impersonated=activity_storage.get_was_impersonated(),
        item_id=account.id,
        scope=ACTIVITY_SCOPE,
        activity=activity,
        detail=Detail(
            name=account.name,
            changes=[
                Change(
                    type=ACTIVITY_SCOPE,
                    action="changed",
                    field=definition.name,
                    before=previous_user.email if previous_user is not None else None,
                    after=current_user.email if current_user is not None else None,
                )
            ],
            context=context,
        ),
        instance_only=True,
    )
    if entry is None:
        raise RuntimeError("Account relationship activity entry could not be built")
    # bulk_create skips post_save, whose receiver publishes the entry to Kafka at once; the publish
    # waits for the commit so a rolled-back mutation never announces itself.
    ActivityLog.objects.bulk_create([entry])
    transaction.on_commit(lambda: post_save.send(sender=ActivityLog, instance=entry, created=True))
    if emit_event:
        _schedule_relationship_changed_event(
            account=account,
            definition=definition,
            previous_user=previous_user,
            current_user=current_user,
            actor=actor,
        )


def _schedule_relationship_changed_event(
    *,
    account: Account,
    definition: AccountRelationshipDefinition,
    previous_user: User | None,
    current_user: User | None,
    actor: Actor,
) -> None:
    """Emit only after the relationship write commits, without failing the write on capture errors."""

    def emit() -> None:
        try:
            emit_account_relationship_changed(
                account=account,
                definition=definition,
                previous_user=previous_user,
                current_user=current_user,
                actor=actor.user,
                workflow_id=actor.workflow_id,
            )
        except Exception as error:
            capture_exception(error)

    transaction.on_commit(emit)
