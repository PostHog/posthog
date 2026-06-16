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

import sys
import json
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
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit a single JSON object to stdout (consumed by the agent-console setup script).",
        )

    def handle(self, *args, **options):
        # SECURITY: this command provisions an `is_first_party=True` OAuth app,
        # which skips the OAuth consent screen for EVERY org/user. That's fine
        # for a throwaway local-dev app, but it must NEVER be created this way
        # in a real deployment — prod's first-party app is provisioned by ops
        # through the admin UI with appropriate scoping. These two guards are
        # the control that keeps the consent-skip blast radius local-only; do
        # not relax them. (`DEBUG` is False in every deployed environment;
        # `CLOUD_DEPLOYMENT` is the belt-and-braces catch for a misconfig.)
        if not settings.DEBUG:
            raise CommandError("This command can only run with DEBUG=True")
        if settings.CLOUD_DEPLOYMENT:
            raise CommandError("This command cannot run in cloud deployments")

        redirect_uri = options["redirect_uri"]
        keep_secret = options["keep_secret"]
        as_json = options["json"]

        existing = OAuthApplication.objects.filter(client_id=DEV_CLIENT_ID).first()

        if existing and keep_secret:
            if as_json:
                self._emit_json(client_id=DEV_CLIENT_ID, client_secret=None, redirect_uri=existing.redirect_uris)
                return
            print(f"OAuth app already exists for client_id={DEV_CLIENT_ID}; secret unchanged.")
            print(f"Redirect URIs: {existing.redirect_uris}")
            return

        new_secret = secrets.token_urlsafe(48)

        if existing:
            existing.client_secret = new_secret
            existing.redirect_uris = redirect_uri
            # First-party so the console skips the OAuth consent screen — it's a
            # native PostHog app, not a third-party integration.
            existing.is_first_party = True
            existing.save(update_fields=["client_secret", "redirect_uris", "is_first_party"])
            status = "rotated"
        else:
            OAuthApplication.objects.create(
                name=DEV_APP_NAME,
                client_id=DEV_CLIENT_ID,
                client_secret=new_secret,
                client_type="confidential",
                authorization_grant_type="authorization-code",
                redirect_uris=redirect_uri,
                algorithm="RS256",
                # Native first-party app — skips the OAuth consent screen.
                is_first_party=True,
            )
            status = "created"

        if as_json:
            self._emit_json(client_id=DEV_CLIENT_ID, client_secret=new_secret, redirect_uri=redirect_uri)
            return

        if status == "rotated":
            print(f"Rotated client_secret for existing OAuth app (client_id={DEV_CLIENT_ID}).")
        else:
            print(f"Created OAuth app (client_id={DEV_CLIENT_ID}).")
        print()
        print("Paste into services/agent-console/.env.local:")
        print()
        print(f"POSTHOG_OAUTH_CLIENT_ID={DEV_CLIENT_ID}")
        print(f"POSTHOG_OAUTH_CLIENT_SECRET={new_secret}")
        print()
        print(f"Redirect URI registered: {redirect_uri}")

    def _emit_json(self, *, client_id: str, client_secret: str | None, redirect_uri: str) -> None:
        # Emit ONLY the JSON to stdout so callers can parse it cleanly even
        # when Django startup logs are noisy on stderr. Set verbosity=0 on
        # invocation to keep stdout single-line.
        sys.stdout.write(
            json.dumps(
                {
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "redirectUri": redirect_uri,
                }
            )
        )
        sys.stdout.write("\n")
