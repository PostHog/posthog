from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import STRIPE_POSTHOG_SECRET_NAMES, Integration, StripeIntegration
from posthog.models.integration.stripe import revoke_team_oauth_tokens
from posthog.models.oauth import OAuthApplication


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

                # Mint before revoking. Revoking first strands the customer whenever the Stripe
                # write fails, because their app keeps reading a token that no longer exists.
                publication = stripe_integration.write_posthog_secrets(integration.team_id, created_by)
                if publication.unwritten and len(publication.unwritten) < len(STRIPE_POSTHOG_SECRET_NAMES):
                    raise PartialStripeWrite(
                        f"Stripe secret store partially updated, unwritten: {', '.join(publication.unwritten)}. "
                        "Old and new tokens both left in place; this integration needs manual repair."
                    )
                if publication.unwritten:
                    raise RuntimeError(f"Stripe secret store not updated: {', '.join(publication.unwritten)}")

                revoke_team_oauth_tokens(
                    StripeIntegration._posthog_oauth_apps_for_revocation(),
                    integration.team_id,
                    keep_access_token_ids=[publication.access_token_id] if publication.access_token_id else [],
                )
            except Exception as e:
                # write_posthog_secrets already drops a credential that never reached Stripe, and a
                # partial write must keep both, so there is nothing to unwind here.
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
