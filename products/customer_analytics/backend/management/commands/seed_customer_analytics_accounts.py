"""Seed Customer analytics accounts from a project's existing group-analytics groups.

Builds on top of data already in a project (e.g. demo data) instead of generating events,
so it has no dependency on ClickHouse->Postgres sync timing. For the given team it:

- reads the group-analytics groups at index 0,
- creates an Account for each (external_id = group key, so the account org page resolves),
- ensures a small shared pool of organization-member users and assigns them as each account's
  CSM / account executive / account owner,
- adds a few notes (internal notebooks) to a handful of accounts,
- points the team's customer-analytics config at group type index 0.

Re-running is safe: existing accounts, pool users, and notes are left alone.

Usage:
    python manage.py seed_customer_analytics_accounts --team-id 1
    python manage.py seed_customer_analytics_accounts --team-id 1 --users 5 --accounts-with-notes 5
    python manage.py seed_customer_analytics_accounts --team-id 1 --dry-run
"""

from typing import Any
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models import OrganizationMembership, Team, User
from posthog.models.scoping import team_scope
from posthog.persons_db import persons_db_connection

from products.customer_analytics.backend.models.account import Account, AccountAssignment, AccountProperties
from products.customer_analytics.backend.models.team_customer_analytics_config import TeamCustomerAnalyticsConfig
from products.notebooks.backend.facade import api as notebooks

ACCOUNT_GROUP_TYPE_INDEX = 0

NOTE_TEMPLATES: list[tuple[str, str]] = [
    ("Kickoff call", "Walked the team through onboarding. Main goal is consolidating file storage across departments."),
    ("QBR summary", "Reviewed usage trends — uploads up month over month. Flagged seats approaching the plan limit."),
    ("Renewal notes", "Renewal in ~60 days. Champion is happy; needs finance sign-off on the enterprise tier."),
    ("Support escalation", "Looked into slow shared-link loads. Mitigated for now; permanent fix ETA to follow."),
]


class Command(BaseCommand):
    help = "Seed Customer analytics accounts (with users and notes) from existing group-analytics groups."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team whose groups to read and seed into.")
        parser.add_argument(
            "--users",
            type=int,
            default=5,
            help="Size of the org-member user pool to create and assign as account roles (default: 5).",
        )
        parser.add_argument(
            "--accounts-with-notes", type=int, default=5, help="How many accounts get notes (default: 5)."
        )
        parser.add_argument(
            "--notes-per-account", type=int, default=2, help="Notes created per selected account (default: 2)."
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Cap how many groups become accounts (default: all)."
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing.")

    def handle(self, *args: Any, **options: Any) -> None:
        team = self._get_team(options["team_id"])
        groups = self._read_account_groups(team, options["limit"])
        if not groups:
            raise CommandError(f"No group-analytics groups at index {ACCOUNT_GROUP_TYPE_INDEX} for team {team.pk}.")

        self.stdout.write(
            f"Found {len(groups)} group(s) at index {ACCOUNT_GROUP_TYPE_INDEX} for team {team.pk} ({team.name})."
        )

        if options["dry_run"]:
            note_account_count = min(options["accounts_with_notes"], len(groups))
            self.stdout.write(self.style.WARNING("Dry run — no changes will be written."))
            self.stdout.write(
                f"Would set account_group_type_index = {ACCOUNT_GROUP_TYPE_INDEX}, "
                f"create up to {len(groups)} account(s), ensure a pool of {options['users']} user(s), "
                f"and add up to {note_account_count * options['notes_per_account']} note(s) "
                f"across {note_account_count} account(s)."
            )
            return

        self._set_config(team)
        user_pool = self._ensure_user_pool(team, options["users"])
        accounts = self._create_accounts(team, groups, user_pool)
        self._create_notes(team, accounts, user_pool, options["accounts_with_notes"], options["notes_per_account"])
        self.stdout.write(self.style.SUCCESS("Done."))

    def _get_team(self, team_id: int) -> Team:
        try:
            return Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} does not exist.")

    def _read_account_groups(self, team: Team, limit: int | None) -> list[tuple[str, dict[str, Any]]]:
        query = (
            "SELECT group_key, group_properties FROM posthog_group "
            "WHERE team_id = %(team_id)s AND group_type_index = %(gti)s ORDER BY group_key"
        )
        with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
            cursor.execute(query, {"team_id": team.pk, "gti": ACCOUNT_GROUP_TYPE_INDEX})
            rows = [(group_key, props or {}) for group_key, props in cursor.fetchall()]
        return rows[:limit] if limit is not None else rows

    def _set_config(self, team: Team) -> None:
        # Point customer analytics at the group type we seed from, so the accounts list and the
        # account org page's usage metrics resolve against it.
        TeamCustomerAnalyticsConfig.objects.update_or_create(
            team=team, defaults={"account_group_type_index": ACCOUNT_GROUP_TYPE_INDEX}
        )
        self.stdout.write(f"Set account_group_type_index = {ACCOUNT_GROUP_TYPE_INDEX}.")

    def _ensure_user_pool(self, team: Team, count: int) -> list[User]:
        organization = team.organization
        # Team-scoped email domain keeps pool users unique per team (User.email is globally unique).
        domain = f"team{team.pk}.customer-analytics.invalid"
        pool: list[User] = []
        created = 0
        for i in range(1, count + 1):
            email = f"ca-seed-{i}@{domain}"
            existing = User.objects.filter(email=email).first()
            # Reuse a prior run's seed user, but never adopt a stranger who happens to hold the
            # predictable address into the org — if the email is taken by a non-member, mint a
            # fresh unguessable one instead.
            if (
                existing is not None
                and OrganizationMembership.objects.filter(organization=organization, user=existing).exists()
            ):
                pool.append(existing)
                continue
            if existing is not None:
                email = f"ca-seed-{i}-{uuid4().hex[:8]}@{domain}"
            pool.append(
                User.objects.create_and_join(
                    organization=organization,
                    email=email,
                    password=None,
                    first_name=f"Account Manager {i}",
                    level=OrganizationMembership.Level.MEMBER,
                )
            )
            created += 1
        self.stdout.write(f"Ensured pool of {len(pool)} org member user(s) ({created} created).")
        return pool

    @transaction.atomic
    def _create_accounts(
        self, team: Team, groups: list[tuple[str, dict[str, Any]]], user_pool: list[User]
    ) -> list[Account]:
        assignments = [AccountAssignment(id=user.id, email=user.email) for user in user_pool]
        creator = team.organization.members.first()
        created = 0
        accounts: list[Account] = []
        with team_scope(team.pk):
            existing = {
                account.external_id: account
                for account in Account.objects.filter(external_id__in=[key for key, _ in groups])
            }
            for index, (group_key, props) in enumerate(groups):
                account = existing.get(group_key)
                if account is None:
                    account = Account.objects.create_account(
                        team=team,
                        name=props.get("name") or group_key,
                        external_id=group_key,
                        created_by=creator,
                        properties=self._account_roles(assignments, index, group_key),
                    )
                    created += 1
                accounts.append(account)
        self.stdout.write(f"Created {created} account(s) ({len(groups) - created} already existed).")
        return accounts

    @staticmethod
    def _account_roles(assignments: list[AccountAssignment], index: int, group_key: str) -> AccountProperties:
        count = len(assignments)
        return AccountProperties(
            csm=assignments[index % count] if count else None,
            account_executive=assignments[(index + 1) % count] if count else None,
            account_owner=assignments[(index + 2) % count] if count else None,
            stripe_customer_id=f"cus_{group_key[:14]}",
        )

    @transaction.atomic
    def _create_notes(
        self,
        team: Team,
        accounts: list[Account],
        user_pool: list[User],
        accounts_with_notes: int,
        notes_per_account: int,
    ) -> None:
        if accounts_with_notes <= 0 or notes_per_account <= 0:
            return
        author = user_pool[0] if user_pool else team.organization.members.first()
        created = 0
        selected = accounts[:accounts_with_notes]
        for account in selected:
            if account.notebooks.exists():  # keep re-runs idempotent — don't pile on
                continue
            for note_index in range(notes_per_account):
                title, body = NOTE_TEMPLATES[note_index % len(NOTE_TEMPLATES)]
                notebooks.create_account_notebook(
                    team.id,
                    account.id,
                    title=f"{account.name} — {title}",
                    content=_paragraph_doc(body),
                    text_content=body,
                    created_by_id=author.id if author else None,
                    last_modified_by_id=author.id if author else None,
                )
                created += 1
        self.stdout.write(f"Created {created} note(s) across up to {len(selected)} account(s).")


def _paragraph_doc(text: str) -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
