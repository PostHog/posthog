# ruff: noqa: T201 allow print statements
"""
Provision the OAuth application the agent console uses for local development.

Run once per dev environment. Output is the `client_id` + `client_secret`
the console expects in `services/agent-console/.env.local`:

    POSTHOG_OAUTH_CLIENT_ID=<client_id>
    POSTHOG_OAUTH_CLIENT_SECRET=<client_secret>

Idempotent: re-running rotates the client_secret (and re-prints it) but
keeps the deterministic client_id so anything cached against the dev
app keeps working.

In prod the equivalent OAuth app is created by ops via the PostHog admin
UI and the credentials are supplied via the deploy's env.
"""

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.oauth import OAuthApplication

DEV_CLIENT_ID = "agent-console-dev"
DEV_APP_NAME = "Agent Console (local dev)"
DEV_REDIRECT_URI = "http://localhost:3040/api/auth/callback"


class Command(BaseCommand):
    help = "Provision the OAuth app the agent console uses for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--redirect-uri",
            type=str,
            default=DEV_REDIRECT_URI,
            help=f"Redirect URI for the console's OAuth callback (default: {DEV_REDIRECT_URI})",
        )
        parser.add_argument(
            "--keep-secret",
            action="store_true",
            help="Don't rotate the client_secret if the app already exists (won't re-print it either).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only run with DEBUG=True")
        if settings.CLOUD_DEPLOYMENT:
            raise CommandError("This command cannot run in cloud deployments")

        redirect_uri = options["redirect_uri"]
        keep_secret = options["keep_secret"]

        existing = OAuthApplication.objects.filter(client_id=DEV_CLIENT_ID).first()

        if existing and keep_secret:
            print(f"OAuth app already exists for client_id={DEV_CLIENT_ID}; secret unchanged.")
            print(f"Redirect URIs: {existing.redirect_uris}")
            return

        new_secret = secrets.token_urlsafe(48)

        if existing:
            existing.client_secret = new_secret
            existing.redirect_uris = redirect_uri
            existing.save(update_fields=["client_secret", "redirect_uris"])
            print(f"Rotated client_secret for existing OAuth app (client_id={DEV_CLIENT_ID}).")
        else:
            OAuthApplication.objects.create(
                name=DEV_APP_NAME,
                client_id=DEV_CLIENT_ID,
                client_secret=new_secret,
                client_type="confidential",
                authorization_grant_type="authorization-code",
                redirect_uris=redirect_uri,
                algorithm="RS256",
            )
            print(f"Created OAuth app (client_id={DEV_CLIENT_ID}).")

        print()
        print("Paste into services/agent-console/.env.local:")
        print()
        print(f"POSTHOG_OAUTH_CLIENT_ID={DEV_CLIENT_ID}")
        print(f"POSTHOG_OAUTH_CLIENT_SECRET={new_secret}")
        print()
        print(f"Redirect URI registered: {redirect_uri}")
