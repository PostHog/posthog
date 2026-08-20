from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import STRIPE_POSTHOG_SECRET_NAMES, Integration, StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken, lock_oauth_connection


class PartialStripeWrite(Exception):
    """Some secrets reached Stripe and some did not, so neither credential is safe to delete."""


class Command(BaseCommand):
    help = (
        "Rotate PostHog OAuth tokens for every Stripe marketplace integration onto the "
        "post-split OAuth application, and rewrite the corresponding Stripe Secret Store entries. "
        "Needed because tokens minted before the application split stay valid on the old, "
        "shared application until explicitly revoked."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be rotated without revoking tokens, minting replacements, or calling Stripe",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Rotate a single team's Stripe integration only, for testing before a full run",
        )

    def _sweep_superseded_tokens(self, team_id: int, created_by_id: int, stale_token_ids: list[int]) -> None:
        """Remove every credential for this team except the replacement just minted.

        Queried inside the lock rather than deleted by the ids snapshotted before minting: a
        holder of the legacy refresh token can exchange it while Stripe is being written, and
        that mints a pair the snapshot never saw.

        `lock_oauth_connection` is what serializes this against the minting side. Row locks alone
        are not enough, for the reason its docstring gives: a blocked sweep re-checks the locked
        row without widening its snapshot, so a token inserted meanwhile survives.
        """
        apps = StripeIntegration._posthog_oauth_apps_for_revocation()

        with transaction.atomic():
            user_ids = (
                set(
                    OAuthAccessToken.objects.filter(application__in=apps, scoped_teams__contains=[team_id]).values_list(
                        "user_id", flat=True
                    )
                )
                | set(
                    OAuthRefreshToken.objects.filter(
                        application__in=apps, scoped_teams__contains=[team_id]
                    ).values_list("user_id", flat=True)
                )
                | {created_by_id}
            )
            # Before any row lock and in a fixed order, matching the minting side, so the two
            # cannot deadlock against each other.
            for user_id, application_id in sorted(
                (user_id, app.id) for user_id in user_ids if user_id is not None for app in apps
            ):
                lock_oauth_connection(user_id=user_id, application_id=application_id)

            superseded_ids = list(
                OAuthAccessToken.objects.filter(application__in=apps, scoped_teams__contains=[team_id])
                .exclude(id__in=self._replacement_token_ids(team_id, stale_token_ids))
                .values_list("id", flat=True)
            )

            # Neither direction of the access/refresh link is reliably populated, so match both.
            source_refresh_ids = [
                refresh_id
                for refresh_id in OAuthAccessToken.objects.filter(id__in=superseded_ids).values_list(
                    "source_refresh_token_id", flat=True
                )
                if refresh_id is not None
            ]
            OAuthRefreshToken.objects.filter(
                Q(access_token_id__in=superseded_ids) | Q(id__in=source_refresh_ids)
            ).delete()
            OAuthAccessToken.objects.filter(id__in=superseded_ids).delete()

    @staticmethod
    def _replacement_token_ids(team_id: int, stale_token_ids: list[int]) -> list[int]:
        """The tokens minted by this run: on the marketplace application and not in the snapshot.

        A refresh of a leaked legacy credential mints onto the orchestrator's application, so it
        cannot be mistaken for the replacement.
        """
        return list(
            OAuthAccessToken.objects.filter(
                application__client_id=settings.STRIPE_MARKETPLACE_OAUTH_CLIENT_ID,
                scoped_teams__contains=[team_id],
            )
            .exclude(id__in=stale_token_ids)
            .values_list("id", flat=True)
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        team_id: int | None = options.get("team_id")

        if not settings.STRIPE_MARKETPLACE_OAUTH_CLIENT_ID:
            raise CommandError(
                "STRIPE_MARKETPLACE_OAUTH_CLIENT_ID is not set. Rotating now would re-mint tokens onto "
                "the same application these tokens already live on and accomplish nothing."
            )

        if settings.STRIPE_MARKETPLACE_OAUTH_CLIENT_ID == settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
            raise CommandError(
                "STRIPE_MARKETPLACE_OAUTH_CLIENT_ID equals STRIPE_POSTHOG_OAUTH_CLIENT_ID. Rotating now "
                "would re-mint onto the orchestrator's application, which can issue deep links."
            )

        # The application row has to exist before revoking, or rotation strips access with nothing
        # to mint replacements onto.
        if not OAuthApplication.objects.filter(client_id=settings.STRIPE_MARKETPLACE_OAUTH_CLIENT_ID).exists():
            raise CommandError(
                f"No OAuthApplication exists for client_id={settings.STRIPE_MARKETPLACE_OAUTH_CLIENT_ID}. "
                "Revoking tokens now would strip access with nothing to mint replacements onto."
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in DRY RUN mode — no tokens or secrets will change"))

        integrations = Integration.objects.filter(kind="stripe").order_by("id")
        if team_id is not None:
            integrations = integrations.filter(team_id=team_id)

        rotated = 0
        skipped: list[str] = []
        failed: list[str] = []

        for integration in integrations.iterator():
            label = f"integration={integration.id} team={integration.team_id}"
            created_by = integration.created_by

            if created_by is None:
                reason = "no created_by user"
                self.stdout.write(self.style.WARNING(f"  {label}: skipped ({reason})"))
                skipped.append(f"{label}: {reason}")
                continue

            if dry_run:
                self.stdout.write(f"  {label}: would rotate (user={created_by.id})")
                rotated += 1
                continue

            try:
                stripe_integration = StripeIntegration(integration)
                stale_token_ids = list(
                    OAuthAccessToken.objects.filter(
                        application__in=StripeIntegration._posthog_oauth_apps_for_revocation(),
                        scoped_teams__contains=[integration.team_id],
                    ).values_list("id", flat=True)
                )

                # Mint before revoking. Revoking first strands the customer whenever the Stripe
                # write fails, because their app keeps reading a token that no longer exists.
                unwritten = stripe_integration.write_posthog_secrets(integration.team_id, created_by)
                if unwritten and len(unwritten) < len(STRIPE_POSTHOG_SECRET_NAMES):
                    raise PartialStripeWrite(
                        f"Stripe secret store partially updated, unwritten: {', '.join(unwritten)}. "
                        "Old and new tokens both left in place; this integration needs manual repair."
                    )
                if unwritten:
                    raise RuntimeError(f"Stripe secret store not updated: {', '.join(unwritten)}")

                self._sweep_superseded_tokens(integration.team_id, created_by.id, stale_token_ids)
            except Exception as e:
                # A mint that never reached Stripe leaves a credential nobody holds; drop it so
                # retrying does not accumulate one per attempt. A partial write is the opposite:
                # Stripe is already serving the new token for some keys, so deleting it here is
                # what would break the customer.
                if not isinstance(e, PartialStripeWrite):
                    orphaned = OAuthAccessToken.objects.filter(
                        application__in=StripeIntegration._posthog_oauth_apps_for_revocation(),
                        scoped_teams__contains=[integration.team_id],
                    ).exclude(id__in=stale_token_ids)
                    OAuthRefreshToken.objects.filter(access_token__in=orphaned).delete()
                    orphaned.delete()

                capture_exception(e, {"integration_id": integration.id, "team_id": integration.team_id})
                self.stdout.write(self.style.ERROR(f"  {label}: failed ({e})"))
                failed.append(f"{label}: {e}")
                continue

            self.stdout.write(self.style.SUCCESS(f"  {label}: rotated"))
            rotated += 1

        verb = "Would rotate" if dry_run else "Rotated"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{verb}: {rotated}"))
        self.stdout.write(f"Skipped: {len(skipped)}")
        for line in skipped:
            self.stdout.write(f"  - {line}")
        self.stdout.write(f"Failed: {len(failed)}")
        for line in failed:
            self.stdout.write(f"  - {line}")
