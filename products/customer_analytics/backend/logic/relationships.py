"""
Assign/end transactions for account relationships: the one write path for every relationship
writer (UI API, external API, AI tool, workflows, management commands). Each mutation locks the
Account row, applies the controlled-relationship policy, advances the control timestamp when
customer analytics controls that relationship on the account, and writes its activity row inside
the same transaction, so a mutation without an audit record cannot commit. The Salesforce claim
procedure in ``logic/ownership_claims.py`` writes through the public helpers here under the same
lock and audit rules.
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
from posthog.models.user import User

from products.customer_analytics.backend.events import emit_account_relationship_changed
from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import ownership
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipControl,
    AccountRelationshipDefinition,
)

ACTIVITY_SCOPE = "Account"


class AccountRelationshipNotFound(Exception):
    pass


class ManagedRolePolicyError(Exception):
    """An autonomous writer tried to change a controlled relationship that customer analytics manages
    on the account."""


class ProtectedRelationshipHistoryError(Exception):
    """A row under a controlled definition cannot be hard-deleted; end it instead."""


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


@dataclasses.dataclass(frozen=True)
class AccountRelationshipActivityContext(ActivityContextBase):
    """Provenance stored beside the change so a reader can tell which writer acted, through which
    reference, and where the control timestamp stood afterwards (null where the relationship is not
    managed on the account)."""

    relationship_id: str | None
    definition_id: str
    definition_name: str
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
    the current holder again is a no-op that records nothing."""
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account.id)
        control = ownership.control_for(locked_account, definition)
        _enforce_managed_role_policy(control, actor)
        # A controlled definition is single-holder by invariant, and the caller's copy of the
        # definition may predate control starting, so a managed relationship always hands off.
        single_holder = definition.is_single_holder or control is not None
        active = list(active_relationships(team_id, locked_account, definition))
        existing = next((rel for rel in active if rel.user_id == user.id), None)
        if existing is not None:
            return existing
        if active and single_holder and not replace_active:
            raise RelationshipOccupiedError(str(definition.id))

        previous_user = active[0].user if single_holder and active else None
        if single_holder:
            end_rows(team_id, active)
        relationship = AccountRelationship.objects.for_team(team_id).create(
            team_id=team_id,
            account=locked_account,
            definition=definition,
            user=user,
            created_by=actor.user,
            source=actor.source,
        )
        controlled_at = _advance_if_managed(control)
        record_transition(
            account=locked_account,
            actor=actor,
            activity="relationship_assigned",
            definition=definition,
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

    On a managed relationship, clearing an already-empty one is still a decision: the fence advances
    and the confirmation is recorded, so a later automated claim cannot treat it as never reviewed.
    """
    with transaction.atomic():
        locked_account = _lock_or_raise(team_id, account.id)
        control = ownership.control_for(locked_account, definition)
        _enforce_managed_role_policy(control, actor)
        active = list(active_relationships(team_id, locked_account, definition))
        if not active and control is None:
            return 0

        end_rows(team_id, active)
        controlled_at = _advance_if_managed(control)
        if not active:
            record_transition(
                account=locked_account,
                actor=actor,
                activity="role_confirmed_empty",
                definition=definition,
                relationship=None,
                previous_user=None,
                current_user=None,
                controlled_at=controlled_at,
                emit_event=False,
            )
            return 0
        for relationship in active:
            record_transition(
                account=locked_account,
                actor=actor,
                activity="relationship_ended",
                definition=definition,
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
        control = ownership.control_for(locked_account, relationship.definition)
        _enforce_managed_role_policy(control, actor)

        end_rows(team_id, [relationship])
        controlled_at = _advance_if_managed(control)
        record_transition(
            account=locked_account,
            actor=actor,
            activity="relationship_ended",
            definition=relationship.definition,
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
    """Hard-delete one relationship row, active or ended. Rows under a controlled definition are
    history other systems replay against and are refused."""
    with transaction.atomic():
        definition_id = (
            AccountRelationship.objects.for_team(team_id)
            .filter(id=relationship_id, account_id=account_id)
            .values_list("definition_id", flat=True)
            .first()
        )
        if definition_id is None:
            raise AccountRelationshipNotFound(relationship_id)
        # Definition before account, the order every writer takes, so control cannot start between
        # the check below and the delete.
        definition = ownership.lock_definition(team_id, definition_id)
        locked_account = _lock_or_raise(team_id, account_id, missing_id=relationship_id)
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("user")
            .filter(id=relationship_id, account=locked_account)
            .first()
        )
        if relationship is None or definition is None:
            raise AccountRelationshipNotFound(relationship_id)
        if definition.is_controlled:
            raise ProtectedRelationshipHistoryError(relationship_id)

        was_active = relationship.ended_at is None
        deleted_id = str(relationship.id)
        relationship.delete()
        record_transition(
            account=locked_account,
            actor=actor,
            activity="relationship_deleted",
            definition=definition,
            relationship=None,
            relationship_id=deleted_id,
            previous_user=relationship.user,
            current_user=None,
            controlled_at=None,
            emit_event=was_active,
        )


class DefinitionNotControlledError(Exception):
    """The definition is not one customer analytics may take control of, so no account can be
    enrolled under it."""


def enroll(
    *, team_id: int, account: Account, definition: AccountRelationshipDefinition, actor: Actor
) -> AccountRelationshipControl:
    """Take authority over the relationship on this account and return the control row.

    The current holder, if any, is kept: enrollment records that the relationship's state has been
    reviewed, so enrolling an empty relationship confirms it empty. Enrolling twice is a no-op that
    keeps the existing fence.
    """
    with transaction.atomic():
        # Definition before account, the order every writer takes, so `is_controlled` cannot flip
        # between the check below and the insert of the control row.
        locked_definition = ownership.lock_definition(team_id, definition.id)
        if locked_definition is None or not locked_definition.is_controlled:
            raise DefinitionNotControlledError(str(definition.id))
        locked_account = _lock_or_raise(team_id, account.id)
        control = ownership.control_for(locked_account, locked_definition)
        if control is not None:
            return control
        holder = active_relationships(team_id, locked_account, locked_definition).first()
        holder_user = holder.user if holder is not None else None
        control = ownership.enroll(locked_account, locked_definition, actor.user)
        record_transition(
            account=locked_account,
            actor=actor,
            activity="role_enrolled",
            definition=locked_definition,
            relationship=holder,
            previous_user=holder_user,
            current_user=holder_user,
            controlled_at=control.controlled_at,
            emit_event=False,
        )
        return control


def end_rows(team_id: int, rows: list[AccountRelationship]) -> None:
    if not rows:
        return
    ended_at = timezone.now()
    AccountRelationship.objects.for_team(team_id).filter(id__in=[row.id for row in rows]).update(ended_at=ended_at)
    for row in rows:
        row.ended_at = ended_at


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


class _DefinitionSetChanged(Exception):
    pass


def lock_account_and_its_definitions(
    team_id: int, account_id: str | UUID
) -> tuple[Account | None, list[AccountRelationshipDefinition]]:
    """Lock the account and every definition it holds relationship rows under, definitions first
    and by id, the order every other writer takes, so no definition can become controlled while the
    account's rows are judged. Call inside ``transaction.atomic()``.

    A row assigned between the snapshot of definition ids and the account lock would sit under an
    unlocked definition. Rolling the savepoint back releases the locks taken so far, and the snapshot
    is taken again; once the account lock is held no more rows can appear.
    """
    rows = AccountRelationship.objects.for_team(team_id).filter(account_id=account_id)
    for _ in range(3):
        definition_ids = set(rows.values_list("definition_id", flat=True))
        try:
            with transaction.atomic():
                definitions = ownership.lock_definitions(team_id, definition_ids)
                account = lock_account(team_id, account_id)
                if account is not None and not set(rows.values_list("definition_id", flat=True)) <= definition_ids:
                    raise _DefinitionSetChanged()
                return account, definitions
        except _DefinitionSetChanged:
            continue
    raise RuntimeError(f"Relationships kept being added to account {account_id} while it was being locked")


def _lock_or_raise(team_id: int, account_id: str | UUID, *, missing_id: str | None = None) -> Account:
    """Lock the account for the caller's transaction, or report what the caller was asked about as
    not found: the account itself, or ``missing_id`` where the caller named a relationship."""
    account = lock_account(team_id, account_id)
    if account is None:
        raise AccountRelationshipNotFound(missing_id or str(account_id))
    return account


def active_relationships(
    team_id: int, account: Account, definition: AccountRelationshipDefinition
) -> QuerySet[AccountRelationship]:
    return (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition=definition, ended_at__isnull=True)
        .select_related("user")
        .order_by("started_at")
    )


def _enforce_managed_role_policy(control: AccountRelationshipControl | None, actor: Actor) -> None:
    """Only a person may change a relationship the account manages.

    Transfers and clears of managed relationships are human acts. An autonomous writer may still
    fill or change a relationship the account does not manage. Reviewed adoption reaches a managed
    relationship only through ``enroll``, which is the act of taking it over. A new kind of writer
    must be authorized here explicitly before it can alter a reviewed decision. That is why the
    check names the one allowed source rather than the refused ones.
    """
    if control is not None and actor.source != AccountRelationshipSource.HUMAN:
        raise ManagedRolePolicyError(
            f"A {actor.source} writer cannot change a controlled relationship on an account where it is managed"
        )


def _advance_if_managed(control: AccountRelationshipControl | None) -> datetime | None:
    return ownership.advance(control) if control is not None else None


def record_transition(
    *,
    account: Account,
    actor: Actor,
    activity: str,
    definition: AccountRelationshipDefinition,
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
