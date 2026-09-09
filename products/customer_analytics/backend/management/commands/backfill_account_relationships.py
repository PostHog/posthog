"""Backfill account relationships from the retired JSON role keys.

One-time cutover companion. ``Account._properties`` used to carry ``csm``,
``account_executive``, and ``account_owner`` assignments, forward-synced into the
relationship tables on every write. Accounts last written before that sync existed never
made it into the table. Per team this command creates the three seeded definitions,
assigns each JSON role holder as an active relationship, then removes the retired keys
from the stored JSON.

Idempotent. Run once per environment, with --dry-run first:

    python manage.py backfill_account_relationships --dry-run
    python manage.py backfill_account_relationships
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import User

from products.customer_analytics.backend.logic import relationships as relationships_logic
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition

ROLE_KEY_TO_DEFINITION_NAME = {
    "csm": "CSM",
    "account_executive": "Account executive",
    "account_owner": "Account owner",
}


class Command(BaseCommand):
    help = "Backfill account relationships from the retired JSON role keys, then strip the keys."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        role_keys = list(ROLE_KEY_TO_DEFINITION_NAME)
        team_ids = (
            Account.objects.unscoped()
            .filter(_properties__has_any_keys=role_keys)
            .values_list("team_id", flat=True)
            .distinct()
        )
        assigned = stripped = 0
        for team_id in team_ids:
            definitions = self._definitions_for_team(team_id, dry_run)
            accounts = Account.objects.for_team(team_id).filter(_properties__has_any_keys=role_keys)
            for account in accounts:
                assigned += self._assign_from_json(team_id, account, definitions, dry_run)
                for key in role_keys:
                    account._properties.pop(key, None)
                if not dry_run:
                    account.save(update_fields=["_properties"])
                stripped += 1
        prefix = "[dry-run] would have " if dry_run else ""
        self.stdout.write(
            f"{prefix}assigned {assigned} relationship(s) and stripped role keys "
            f"from {stripped} account(s) across {len(team_ids)} team(s)."
        )

    @staticmethod
    def _definitions_for_team(team_id: int, dry_run: bool) -> dict[str, AccountRelationshipDefinition | None]:
        definitions: dict[str, AccountRelationshipDefinition | None] = {}
        for key, name in ROLE_KEY_TO_DEFINITION_NAME.items():
            if dry_run:
                definitions[key] = AccountRelationshipDefinition.objects.for_team(team_id).filter(name=name).first()
            else:
                definitions[key] = AccountRelationshipDefinition.objects.for_team(team_id).get_or_create(
                    team_id=team_id, name=name
                )[0]
        return definitions

    @staticmethod
    def _assign_from_json(
        team_id: int,
        account: Account,
        definitions: dict[str, AccountRelationshipDefinition | None],
        dry_run: bool,
    ) -> int:
        assigned = 0
        for key, definition in definitions.items():
            assignment = (account._properties or {}).get(key)
            user_id = assignment.get("id") if isinstance(assignment, dict) else None
            if user_id is None:
                continue
            # Only org members resolve because the relationships endpoint returns real emails,
            # so assigning arbitrary global user ids would leak emails of users outside the org.
            user = User.objects.filter(id=user_id, organization_membership__organization__team__id=team_id).first()
            if user is None:
                continue
            if dry_run:
                if definition is None or not _has_active_holder(team_id, account, definition):
                    assigned += 1
                continue
            if definition is None:
                continue
            # The relationships table has been authoritative since the cutover deploy, so only
            # fill gaps and never overwrite an assignment made after it. The check runs under
            # assign's definition lock, or a concurrent assign landing between check and assign
            # would be replaced by the stale JSON holder.
            with transaction.atomic():
                AccountRelationshipDefinition.objects.for_team(team_id).select_for_update().get(id=definition.id)
                if _has_active_holder(team_id, account, definition):
                    continue
                relationships_logic.assign(
                    team_id=team_id,
                    account=account,
                    definition=definition,
                    user=user,
                    created_by=None,
                    emit_event=False,
                )
            assigned += 1
        return assigned


def _has_active_holder(team_id: int, account: Account, definition: AccountRelationshipDefinition) -> bool:
    return (
        AccountRelationship.objects.for_team(team_id)
        .filter(account=account, definition=definition, ended_at__isnull=True)
        .exists()
    )
