"""
Assign/end transactions for account relationships. Called by the facade and
product-internal account writers only.
"""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.user import User

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
) -> AccountRelationship:
    with transaction.atomic():
        # Serializes concurrent assigns for this definition; prevents double-insert races.
        AccountRelationshipDefinition.objects.for_team(team_id).select_for_update().get(id=definition.id)
        active = list(
            AccountRelationship.objects.for_team(team_id).filter(
                account=account, definition=definition, ended_at__isnull=True
            )
        )
        existing = next((rel for rel in active if rel.user_id == user.id), None)
        if existing is not None:
            return existing
        if definition.is_single_holder:
            for rel in active:
                rel.ended_at = timezone.now()
                rel.save(update_fields=["ended_at"])
        return AccountRelationship.objects.for_team(team_id).create(
            team_id=team_id, account=account, definition=definition, user=user, created_by=created_by
        )


def end_active(*, team_id: int, account: Account, definition: AccountRelationshipDefinition) -> int:
    return (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition=definition, ended_at__isnull=True)
        .update(ended_at=timezone.now())
    )


def end_relationship(*, team_id: int, account_id: str | UUID, relationship_id: str) -> AccountRelationship:
    with transaction.atomic():
        # Serializes concurrent ends of the same row, matching assign's locking contract.
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("definition", "user")
            .select_for_update(of=("self",))
            .filter(id=relationship_id, account_id=account_id, ended_at__isnull=True)
            .first()
        )
        if relationship is None:
            raise AccountRelationshipNotFound(relationship_id)
        relationship.ended_at = timezone.now()
        relationship.save(update_fields=["ended_at"])
    return relationship
