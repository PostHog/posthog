"""Seed account ownership (AE / CSM assignments) from a CSV exported from the billing service.

One-time bridge for making customer analytics the source of truth for account
ownership: the billing repo's ``export_account_ownership`` command dumps the
current assignments from Vitally as ``org_id, account_name, ae_email, ae_name,
csm_email, csm_name`` rows, and this command applies them here.

Emails are resolved to users via the team organization's memberships; rows
whose emails don't resolve (e.g. AEs who have left) are reported for manual
follow-up and that role is left untouched. A blank email in the CSV means
"role unassigned" and clears it. Writes go through
``facade.update_external_account`` so the stored assignments carry the same
validation as the external API.

Re-running is idempotent against the CSV — but note it overwrites manual edits
made in the UI for the roles present in the file.

Usage:
    python manage.py seed_account_ownership_from_csv --team-id 2 --csv ownership.csv --dry-run
    python manage.py seed_account_ownership_from_csv --team-id 2 --csv ownership.csv --create-missing
"""

import csv
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError

from posthog.models import OrganizationMembership, Team
from posthog.models.scoping import team_scope

from products.customer_analytics.backend.facade import api as facade
from products.customer_analytics.backend.models.account import Account

EXPECTED_COLUMNS = {"org_id", "account_name", "ae_email", "ae_name", "csm_email", "csm_name"}

ROLE_COLUMNS = {"account_executive": "ae_email", "csm": "csm_email"}


class Command(BaseCommand):
    help = "Seed AE / CSM account assignments from a billing-service ownership CSV export."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team whose accounts to update.")
        parser.add_argument("--csv", required=True, help="Path to the ownership CSV export.")
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Create accounts (name from the CSV) for org ids with no matching account.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")

    def handle(self, *args: Any, **options: Any) -> None:
        team = self._get_team(options["team_id"])
        rows = self._read_rows(options["csv"])
        self.stdout.write(f"Read {len(rows)} row(s) for team {team.pk} ({team.name}).")

        users_by_email = self._resolve_users(team, rows)

        created = 0
        updated = 0
        failed = 0
        missing_accounts: list[str] = []
        unresolved: dict[str, list[str]] = {}

        with team_scope(team.pk):
            existing_ids = set(
                Account.objects.filter(external_id__in=[row["org_id"] for row in rows]).values_list(
                    "external_id", flat=True
                )
            )

        for row in rows:
            org_id = row["org_id"]

            role_assignments: dict[str, Optional[int]] = {}
            for role_field, email_column in ROLE_COLUMNS.items():
                email = (row.get(email_column) or "").strip().lower()
                if not email:
                    role_assignments[role_field] = None
                    continue
                user_id = users_by_email.get(email)
                if user_id is None:
                    # Unresolvable is not the same as unassigned: leave the role
                    # untouched and surface it for manual follow-up.
                    unresolved.setdefault(email, []).append(org_id)
                    continue
                role_assignments[role_field] = user_id

            account_exists = org_id in existing_ids
            if not account_exists and not options["create_missing"]:
                missing_accounts.append(org_id)
                continue

            if options["dry_run"]:
                created += 0 if account_exists else 1
                updated += 1 if account_exists else 0
                continue

            if not account_exists:
                Account.objects.create_account(team=team, name=row["account_name"] or org_id, external_id=org_id)
                created += 1

            result = facade.update_external_account(
                team.pk, org_id, role_assignments=role_assignments, tags=None, tags_mode="add"
            )
            if result.account is None:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{org_id}: update failed ({result.error and result.error.value})"))
            elif account_exists:
                updated += 1

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no changes were written."))
            self.stdout.write(f"Would create {created} account(s) and update {updated}.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Created {created} account(s), updated {updated}, {failed} failed."))

        if missing_accounts:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(missing_accounts)} org id(s) have no account (re-run with --create-missing to create): "
                    + ", ".join(missing_accounts[:20])
                    + ("…" if len(missing_accounts) > 20 else "")
                )
            )
        if unresolved:
            self.stdout.write(self.style.WARNING(f"{len(unresolved)} email(s) did not resolve to an org member:"))
            for email, org_ids in sorted(unresolved.items()):
                sample = ", ".join(org_ids[:10]) + ("…" if len(org_ids) > 10 else "")
                self.stdout.write(f"  {email} ({len(org_ids)} account(s): {sample})")

    def _get_team(self, team_id: int) -> Team:
        try:
            return Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} does not exist.")

    def _read_rows(self, path: str) -> list[dict[str, str]]:
        try:
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                columns = set(reader.fieldnames or [])
                if not EXPECTED_COLUMNS.issubset(columns):
                    raise CommandError(
                        f"CSV is missing columns: {sorted(EXPECTED_COLUMNS - columns)} (found {sorted(columns)})"
                    )
                rows = [row for row in reader if (row.get("org_id") or "").strip()]
        except OSError as e:
            raise CommandError(f"Could not read {path}: {e}")
        if not rows:
            raise CommandError("CSV contains no rows with an org_id.")
        return rows

    def _resolve_users(self, team: Team, rows: list[dict[str, str]]) -> dict[str, int]:
        """Map every distinct CSV email (lowercased) to the org member's user id."""
        emails = {
            email
            for row in rows
            for column in ROLE_COLUMNS.values()
            if (email := (row.get(column) or "").strip().lower())
        }
        users_by_email: dict[str, int] = {}
        memberships = OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user__email__in=emails
        ).select_related("user")
        for membership in memberships:
            users_by_email[membership.user.email.lower()] = membership.user.id
        # Emails whose casing differs between the CSV and the user record need the
        # per-email iexact fallback; the bulk __in above only catches exact matches.
        for email in emails - set(users_by_email):
            fallback = (
                OrganizationMembership.objects.filter(organization_id=team.organization_id, user__email__iexact=email)
                .select_related("user")
                .first()
            )
            if fallback:
                users_by_email[email] = fallback.user.id
        return users_by_email
