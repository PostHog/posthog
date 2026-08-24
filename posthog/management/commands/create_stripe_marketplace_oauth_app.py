from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.integration import StripeIntegration
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig

APP_NAME = "PostHog Stripe marketplace app"


class Command(BaseCommand):
    help = (
        "Create or reconcile the OAuth application the Stripe marketplace app's token is minted on. "
        "Kept separate from the provisioning orchestrator's application because the marketplace token "
        "is readable by every member of the customer's Stripe account, and capabilities are granted "
        "per application."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--client-id",
            required=True,
            help="Client id for the marketplace application; must match STRIPE_MARKETPLACE_OAUTH_CLIENT_ID",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created or changed without writing",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        client_id: str = options["client_id"]
        dry_run: bool = options["dry_run"]

        if client_id == settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
            raise CommandError(
                "That is the provisioning orchestrator's client id. Sharing one application is the "
                "problem this command exists to fix."
            )

        configured = settings.STRIPE_MARKETPLACE_OAUTH_CLIENT_ID
        if configured and client_id != configured:
            raise CommandError(
                f"This region runs on STRIPE_MARKETPLACE_OAUTH_CLIENT_ID={configured}. Reconciling "
                f"{client_id} would report success while leaving the application in use untouched."
            )

        existing = OAuthApplication.objects.filter(client_id=client_id).first()

        # Mirrors the orchestrator's row so refresh behaves identically; the Stripe app sends no
        # client secret, so a confidential type would reject it.
        desired = {
            "name": APP_NAME,
            "client_secret": "",
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://localhost",
            "algorithm": "RS256",
            "is_provisioning_partner": False,
        }

        if dry_run:
            verb = "would reconcile" if existing else "would create"
            self.stdout.write(f"{verb} {APP_NAME} (client_id={client_id})")
            if existing:
                self.stdout.write(
                    f"  ceiling_scopes: {' '.join(existing.ceiling_scopes)} -> {StripeIntegration.SCOPES}"
                )
            else:
                self.stdout.write(f"  ceiling_scopes: {StripeIntegration.SCOPES}")
            self.stdout.write("  can_issue_deep_links: False")
            return

        app = existing or OAuthApplication(client_id=client_id)
        for field, value in desired.items():
            setattr(app, field, value)
        app.scopes = StripeIntegration.SCOPES.split()
        # ceiling_scopes is scopes + optional_scopes, so leaving optional_scopes alone would keep
        # anything a drifted row carries grantable outside the list this command sets.
        app.optional_scopes = []
        # Assigning a fresh config rather than update_provisioning, which merges: on a drifted row
        # that would leave every capability it does not name switched on.
        app.provisioning = ProvisioningConfig()
        app.save()

        self.stdout.write(self.style.SUCCESS(f"{'Reconciled' if existing else 'Created'} {APP_NAME}"))
        self.stdout.write(f"  client_id: {client_id}")
        self.stdout.write(f"  ceiling_scopes: {' '.join(app.ceiling_scopes)}")
        self.stdout.write("  can_issue_deep_links: False")
        self.stdout.write("")
        self.stdout.write(f"Set STRIPE_MARKETPLACE_OAUTH_CLIENT_ID={client_id} in this region, then deploy.")
