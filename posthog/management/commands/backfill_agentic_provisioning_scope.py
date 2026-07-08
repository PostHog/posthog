import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Rehydrate scoped_teams on existing agentic provisioning OAuth tokens. "
        "Walks live access + refresh tokens for partner OAuth applications and "
        "recomputes scoped_teams via _compute_partner_scoped_teams. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--application-id",
            type=str,
            help="Limit to a single OAuthApplication id. Defaults to every application with provisioning_partner_type set.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute new scope without writing.",
        )

    def handle(self, *args, **options):
        # Local import so the import graph stays small for the management command
        # registry; views.py pulls in a much larger dependency surface than the
        # rest of the command suite.
        from ee.api.agentic_provisioning.views import _compute_partner_scoped_teams

        application_id = options.get("application_id")
        dry_run: bool = options["dry_run"]

        application_qs = OAuthApplication.objects.exclude(provisioning_partner_type="")
        if application_id:
            application_qs = application_qs.filter(id=application_id)

        applications = list(application_qs)
        if not applications:
            self.stdout.write("No matching provisioning partner applications found.")
            return

        total_access = 0
        total_refresh = 0
        changed_access = 0
        changed_refresh = 0
        skipped_empty = 0

        for application in applications:
            self.stdout.write(f"Application {application.id} ({application.name}):")

            # OAuthAccessToken has no `revoked` column (only refresh tokens do); a revoked
            # access token is hard-deleted, so live tokens are the unexpired ones.
            access_tokens = OAuthAccessToken.objects.filter(application=application)
            for access_token in access_tokens.iterator(chunk_size=200):
                total_access += 1
                if access_token.expires and access_token.expires < timezone.now():
                    continue
                user = access_token.user
                if user is None:
                    continue
                old_scope = list(access_token.scoped_teams or [])
                base_team_id = old_scope[0] if old_scope else 0
                new_scope = _compute_partner_scoped_teams(application, user, base_team_id)
                # _compute_partner_scoped_teams returns [] when the base team is gone or the
                # user lost access. An empty scoped_teams is treated as unrestricted by the
                # OAuth permission check (permissions.py), so writing [] here would strip the
                # project restriction from a live token. Leave the existing scope intact and
                # report it for re-authorization, matching the fail-closed issuance/refresh paths.
                if not new_scope:
                    skipped_empty += 1
                    self.stdout.write(
                        f"  access_token={access_token.pk} user={user.id} old={sorted(old_scope)} "
                        f"new=[] (empty scope; left unchanged, needs re-authorization)"
                    )
                    continue
                if sorted(new_scope) == sorted(old_scope):
                    continue
                changed_access += 1
                self.stdout.write(
                    f"  access_token={access_token.pk} user={user.id} old={sorted(old_scope)} new={sorted(new_scope)}"
                )
                if not dry_run:
                    try:
                        with transaction.atomic():
                            locked = OAuthAccessToken.objects.select_for_update().get(pk=access_token.pk)
                            locked.scoped_teams = new_scope
                            locked.save(update_fields=["scoped_teams"])
                    except OAuthAccessToken.DoesNotExist:
                        # A concurrent refresh deleted this row between read and lock; skip
                        # it rather than aborting the whole backfill.
                        self.stdout.write(f"  access_token={access_token.pk} gone before lock; skipping")

            refresh_tokens = OAuthRefreshToken.objects.filter(
                application=application,
                revoked__isnull=True,
            )
            for refresh_token in refresh_tokens.iterator(chunk_size=200):
                total_refresh += 1
                user = refresh_token.user
                if user is None:
                    continue
                old_scope = list(refresh_token.scoped_teams or [])
                base_team_id = old_scope[0] if old_scope else 0
                new_scope = _compute_partner_scoped_teams(application, user, base_team_id)
                # Same fail-closed rule as access tokens: never overwrite a restricted scope
                # with an empty (unrestricted) one. Leave it for re-authorization.
                if not new_scope:
                    skipped_empty += 1
                    self.stdout.write(
                        f"  refresh_token={refresh_token.pk} user={user.id} old={sorted(old_scope)} "
                        f"new=[] (empty scope; left unchanged, needs re-authorization)"
                    )
                    continue
                if sorted(new_scope) == sorted(old_scope):
                    continue
                changed_refresh += 1
                self.stdout.write(
                    f"  refresh_token={refresh_token.pk} user={user.id} old={sorted(old_scope)} new={sorted(new_scope)}"
                )
                if not dry_run:
                    try:
                        with transaction.atomic():
                            locked = OAuthRefreshToken.objects.select_for_update().get(pk=refresh_token.pk)
                            locked.scoped_teams = new_scope
                            locked.save(update_fields=["scoped_teams"])
                    except OAuthRefreshToken.DoesNotExist:
                        # A concurrent refresh removed this row between read and lock; skip
                        # it rather than aborting the whole backfill.
                        self.stdout.write(f"  refresh_token={refresh_token.pk} gone before lock; skipping")

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(
            f"{verb} {changed_access}/{total_access} access tokens and "
            f"{changed_refresh}/{total_refresh} refresh tokens. "
            f"{skipped_empty} tokens left unchanged with empty recomputed scope (need re-authorization)."
        )
