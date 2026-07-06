"""
Assign/end transactions for account relationships, plus the transitional forward-sync from
the legacy JSON role keys. Called by the facade and product-internal account writers only.
"""

from django.db import transaction
from django.utils import timezone

from posthog.models.user import User

from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition

# Legacy Account properties role key -> seeded definition name. Definitions carry no stable
# machine key, so the sync and backfill map role keys to seeded definitions by name.
SEEDED_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("csm", "CSM"),
    ("account_executive", "Account executive"),
    ("account_owner", "Account owner"),
)


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


def end_relationship(*, team_id: int, relationship_id: str) -> AccountRelationship:
    with transaction.atomic():
        # Serializes concurrent ends of the same row, matching assign's locking contract.
        relationship = (
            AccountRelationship.objects.for_team(team_id)
            .select_related("definition", "account")
            .select_for_update(of=("self",))
            .filter(id=relationship_id, ended_at__isnull=True)
            .first()
        )
        if relationship is None:
            raise AccountRelationshipNotFound(relationship_id)
        relationship.ended_at = timezone.now()
        relationship.save(update_fields=["ended_at"])
    return relationship


def sync_from_account_properties(account: Account, *, created_by: User | None = None) -> None:
    """Forward-sync the legacy JSON role keys into the relationships table.

    Transitional: Account._properties is still the source of truth for roles, so every JSON
    role write calls this to keep the table shadowing it — see backend/COMPROMISES.md.
    Roles whose definition doesn't exist yet and unresolvable user ids are skipped; the JSON
    stays authoritative.
    """
    definitions_by_name = {
        definition.name: definition
        for definition in AccountRelationshipDefinition.objects.for_team(account.team_id).filter(
            name__in=[name for _, name in SEEDED_DEFINITIONS]
        )
    }
    properties = account._properties or {}
    for key, name in SEEDED_DEFINITIONS:
        definition = definitions_by_name.get(name)
        if definition is None:
            continue
        assignment = properties.get(key)
        user_id = assignment.get("id") if isinstance(assignment, dict) else None
        if user_id is None:
            end_active(team_id=account.team_id, account=account, definition=definition)
        elif (user := User.objects.filter(id=user_id).first()) is not None:
            assign(team_id=account.team_id, account=account, definition=definition, user=user, created_by=created_by)
