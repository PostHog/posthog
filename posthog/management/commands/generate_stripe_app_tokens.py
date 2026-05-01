"""
Generate PostHog OAuth tokens for the Stripe App in local development.

Reuses existing valid tokens if available, otherwise creates new ones.
Prints the tokens so you can paste them into the Stripe App's dev mode UI.

Usage:
    ./manage.py generate_stripe_app_tokens --team-id=1
    ./manage.py generate_stripe_app_tokens --team-id=1 --force  # always create fresh tokens
"""

import os
import re
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as tz

from oauthlib.common import generate_token

from posthog.models import Team, User
from posthog.models.integration import StripeIntegration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.utils import generate_random_oauth_access_token, generate_random_oauth_refresh_token

STRIPE_APP_NAME = "PostHog Stripe App"
ENV_KEY = "STRIPE_POSTHOG_OAUTH_CLIENT_ID"


def _read_env_value(env_path: str, key: str) -> str | None:
    """Read a value from a .env file, returning None if the key is missing or the file doesn't exist."""
    if not os.path.exists(env_path):
        return None
    with open(env_path) as f:
        for line in f:
            match = re.match(rf"^{re.escape(key)}=(.*)$", line.strip())
            if match:
                return match.group(1).strip().strip("\"'")
    return None


class Command(BaseCommand):
    help = "Generate PostHog OAuth tokens for the Stripe App (local dev only)"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="The team ID to scope the tokens to")
        parser.add_argument(
            "--force", action="store_true", help="Force creation of new tokens even if valid ones exist"
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        force = options["force"]

        team = Team.objects.filter(id=team_id).first()
        if not team:
            raise CommandError(f"Team with id {team_id} does not exist")

        user = User.objects.filter(current_team_id=team_id).first()
        if not user:
            raise CommandError(f"No users found in team with id {team_id}")

        oauth_app = self._get_or_create_oauth_app()

        if not force:
            existing = self._find_existing_tokens(oauth_app, team_id, user.id)
            if existing:
                access_token_value, refresh_token_value, expires = existing
                self._print_tokens(team, user, oauth_app, access_token_value, refresh_token_value, expires, reused=True)
                return

        access_token_value, refresh_token_value, expires = self._create_tokens(oauth_app, team_id, user.id)
        self._print_tokens(team, user, oauth_app, access_token_value, refresh_token_value, expires, reused=False)

    def _find_existing_tokens(
        self, oauth_app: OAuthApplication, team_id: int, user_id: int
    ) -> tuple[str, str, object] | None:
        access_token = (
            OAuthAccessToken.objects.filter(
                application=oauth_app,
                user_id=user_id,
                scoped_teams__contains=[team_id],
                expires__gt=tz.now(),
            )
            .order_by("-expires")
            .first()
        )
        if not access_token:
            return None

        refresh_token = OAuthRefreshToken.objects.filter(
            access_token=access_token,
            user_id=user_id,
            revoked__isnull=True,
        ).first()
        if not refresh_token:
            return None

        return access_token.token, refresh_token.token, access_token.expires

    def _create_tokens(self, oauth_app: OAuthApplication, team_id: int, user_id: int) -> tuple[str, str, object]:
        access_token_value = generate_random_oauth_access_token(None)
        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            token=access_token_value,
            user_id=user_id,
            expires=tz.now() + timedelta(minutes=20),  # Very short-lived to test refreshes locally
            scope=StripeIntegration.SCOPES,
            scoped_teams=[team_id],
        )

        refresh_token_value = generate_random_oauth_refresh_token(None)
        OAuthRefreshToken.objects.create(
            application=oauth_app,
            token=refresh_token_value,
            user_id=user_id,
            access_token=access_token,
            scoped_teams=[team_id],
        )

        return access_token_value, refresh_token_value, access_token.expires

    def _print_tokens(self, team, user, oauth_app, access_token_value, refresh_token_value, expires, *, reused: bool):
        region = "us"

        self.stdout.write("")
        if reused:
            self.stdout.write(self.style.SUCCESS("Reusing existing valid tokens."))
        else:
            self.stdout.write(self.style.SUCCESS("New tokens generated."))
        self.stdout.write("")
        self.stdout.write(f"Team:          {team.name} (id={team.id})")
        self.stdout.write(f"User:          {user.email} (id={user.id})")
        self.stdout.write(f"OAuth App:     {oauth_app.name} (client_id={oauth_app.client_id})")
        self.stdout.write(f"Expires:       {expires}")
        self.stdout.write("")
        self.stdout.write("Paste these into the Stripe App dev mode UI:")
        self.stdout.write("")
        self.stdout.write(
            f"  Region:        {region}  (region only affects which base URL the app uses"
            " — in dev mode both point to localhost)"
        )
        self.stdout.write(f"  Access Token:  {access_token_value}")
        self.stdout.write(f"  Refresh Token: {refresh_token_value}")
        self.stdout.write(f"  Project ID:    {team.id}")
        self.stdout.write(f"  Client ID:     {oauth_app.client_id}")
        self.stdout.write("")

    def _resolve_client_id(self) -> str | None:
        """Resolve the OAuth client ID from the Django setting or directly from .env."""
        # The Django setting is populated if the env var was in the shell environment at startup
        if settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
            return settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID

        # Fall back to reading .env directly — manage.py doesn't load .env into the
        # process environment, so the setting may be empty even though .env has the value
        env_path = os.path.join(settings.BASE_DIR, ".env")
        return _read_env_value(env_path, ENV_KEY)

    def _get_or_create_oauth_app(self) -> OAuthApplication:
        client_id = self._resolve_client_id()

        if client_id:
            try:
                return OAuthApplication.objects.get(client_id=client_id)
            except OAuthApplication.DoesNotExist:
                raise CommandError(
                    f"{ENV_KEY} is set to '{client_id}' but no OAuthApplication with that client_id exists."
                )

        # No client_id configured — check if the app already exists by name
        existing = OAuthApplication.objects.filter(name=STRIPE_APP_NAME).first()
        if existing:
            self._write_client_id_to_env(existing.client_id)
            return existing

        # Create a new OAuthApplication
        self.stdout.write("No OAuthApplication found for the Stripe App, creating one...")
        new_client_id = generate_token()
        oauth_app = OAuthApplication.objects.create(
            name=STRIPE_APP_NAME,
            client_id=new_client_id,
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created OAuthApplication '{STRIPE_APP_NAME}' (client_id={new_client_id})")
        )
        self._write_client_id_to_env(new_client_id)
        return oauth_app

    def _write_client_id_to_env(self, client_id: str) -> None:
        env_path = os.path.join(settings.BASE_DIR, ".env")
        if not os.path.exists(env_path):
            self.stdout.write(self.style.WARNING(f"No .env file found at {env_path}, skipping auto-configuration"))
            self.stdout.write(f"Add this to your .env manually: {ENV_KEY}={client_id}")
            return

        existing_value = _read_env_value(env_path, ENV_KEY)
        if existing_value:
            raise CommandError(
                f"{ENV_KEY} is already in your .env (value: '{existing_value}') "
                f"but no matching OAuthApplication was found in the database. "
                f"Either create the application or remove the stale entry from .env."
            )

        with open(env_path, "a") as f:
            f.write(f"\n{ENV_KEY}={client_id}\n")

        self.stdout.write(self.style.SUCCESS(f"Added {ENV_KEY}={client_id} to .env"))
