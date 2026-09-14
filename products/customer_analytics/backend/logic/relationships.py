"""
Assign/end transactions for account relationships. Called by the facade and
product-internal account writers only.
"""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.exceptions_capture import capture_exception
from posthog.models.user import User

from products.customer_analytics.backend.events import emit_account_relationship_changed
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition


class AccountRelationshipNotFound(Exception):
    pass


def assign(
    *,
    team_id: int,
    account: Account,
    definition: AccountRelationshipDefinition,
    user: User,
    created_by: User | None,
    workflow_id: str | None = None,
    emit_event: bool = True,
) -> AccountRelationship:
    with transaction.atomic():
        # Serializes concurrent assigns for this definition; prevents double-insert races.
        AccountRelationshipDefinition.objects.for_team(team_id).select_for_update().get(id=definition.id)
        active = list(
            AccountRelationship.objects.for_team(team_id)
            .filter(account=account, definition=definition, ended_at__isnull=True)
            .select_related("user")
        )
        existing = next((rel for rel in active if rel.user_id == user.id), None)
        if existing is not None:
            return existing

        previous_user = active[0].user if definition.is_single_holder and active else None
        if definition.is_single_holder:
            for relationship in active:
                relationship.ended_at = timezone.now()
                relationship.save(update_fields=["ended_at"])
        relationship = AccountRelationship.objects.for_team(team_id).create(
            team_id=team_id, account=account, definition=definition, user=user, created_by=created_by
        )
        if emit_event:
            _schedule_relationship_changed_event(
                account=account,
                definition=definition,
                previous_user=previous_user,
                current_user=user,
                actor=created_by,
                workflow_id=workflow_id,
            )
        return relationship


def end_active(
    *,
    team_id: int,
    account: Account,
    definition: AccountRelationshipDefinition,
    actor: User | None = None,
    workflow_id: str | None = None,
    emit_event: bool = True,
) -> int:
    with transaction.atomic():
        active = list(
            AccountRelationship.objects.for_team(team_id)
            .select_related("user")
            .select_for_update(of=("self",))
            .filter(account=account, definition=definition, ended_at__isnull=True)
        )
        if not active:
            return 0
        updated = (
            AccountRelationship.objects.for_team(team_id)
            .filter(id__in=[rel.id for rel in active])
            .update(ended_at=timezone.now())
        )
        if emit_event:
            for relationship in active:
                _schedule_relationship_changed_event(
                    account=account,
                    definition=definition,
                    previous_user=relationship.user,
                    current_user=None,
                    actor=actor,
                    workflow_id=workflow_id,
                )
        return updated


def end_relationship(
    *,
    team_id: int,
    account_id: str | UUID,
    relationship_id: str,
    actor: User | None = None,
    workflow_id: str | None = None,
    emit_event: bool = True,
) -> AccountRelationship:
    with transaction.atomic():
        # Serializes concurrent ends of the same row, matching assign's locking contract.
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("definition", "user", "account__team")
            .select_for_update(of=("self",))
            .filter(id=relationship_id, account_id=account_id, ended_at__isnull=True)
            .first()
        )
        if relationship is None:
            raise AccountRelationshipNotFound(relationship_id)
        relationship.ended_at = timezone.now()
        relationship.save(update_fields=["ended_at"])
        if emit_event:
            _schedule_relationship_changed_event(
                account=relationship.account,
                definition=relationship.definition,
                previous_user=relationship.user,
                current_user=None,
                actor=actor,
                workflow_id=workflow_id,
            )
    return relationship


def delete_relationship(
    *,
    team_id: int,
    account_id: str | UUID,
    relationship_id: str,
    actor: User | None = None,
) -> None:
    with transaction.atomic():
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("definition", "user", "account__team")
            .select_for_update(of=("self",))
            .filter(id=relationship_id, account_id=account_id)
            .first()
        )
        if relationship is None:
            raise AccountRelationshipNotFound(relationship_id)
        was_active = relationship.ended_at is None
        relationship.delete()
        if was_active:
            _schedule_relationship_changed_event(
                account=relationship.account,
                definition=relationship.definition,
                previous_user=relationship.user,
                current_user=None,
                actor=actor,
                workflow_id=None,
            )


def _schedule_relationship_changed_event(
    *,
    account: Account,
    definition: AccountRelationshipDefinition,
    previous_user: User | None,
    current_user: User | None,
    actor: User | None,
    workflow_id: str | None,
) -> None:
    """Emit only after the relationship write commits, without failing the write on capture errors."""

    def emit() -> None:
        try:
            emit_account_relationship_changed(
                account=account,
                definition=definition,
                previous_user=previous_user,
                current_user=current_user,
                actor=actor,
                workflow_id=workflow_id,
            )
        except Exception as error:
            capture_exception(error)

    transaction.on_commit(emit)
