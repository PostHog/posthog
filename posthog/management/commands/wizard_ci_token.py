"""
Mint a long-lived wizard-app OAuth token for the wizard CI smoke test.

Usage:
    python manage.py wizard_ci_token --email ci-bot@example.com --team 2
    python manage.py wizard_ci_token --email ci-bot@example.com --team 2 --days 90

The smoke test runs `wizard --ci --api-key <token>`. A personal API key (phx_)
is refused at the gateway-token mint as `invalid_token`, so CI needs a `pha_`
issued under the wizard OAuth app with `llm_gateway:read`, scoped to one team.
The token is minted the way a cloud wizard run's is (blocklist check, the wizard
app's scope ceiling) and then given a long expiry. It is printed once, on the
last line of output, and stored nowhere else.
"""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models import OAuthAccessToken, Team, User
from posthog.scopes import resolve_ceiling
from posthog.storage.gateway_credential_cache import GATEWAY_CREDENTIAL_REQUIRED_SCOPE
from posthog.temporal.oauth import WizardIdentityBlockedError, create_wizard_oauth_access_token_for_user, get_wizard_app

_DEFAULT_DAYS = 365
_MAX_DAYS = 730


class Command(BaseCommand):
    help = "Mint a long-lived wizard-app OAuth token (pha_) for the wizard CI smoke test."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True, help="the CI bot user's email")
        parser.add_argument("--team", type=int, required=True, help="team id the token is scoped to")
        parser.add_argument("--days", type=int, default=_DEFAULT_DAYS, help=f"lifetime in days (1-{_MAX_DAYS})")

    def handle(self, *args: Any, **options: Any) -> None:
        days = options["days"]
        if days < 1 or days > _MAX_DAYS:
            raise CommandError(f"--days must be between 1 and {_MAX_DAYS}")

        user = User.objects.filter(email__iexact=options["email"]).first()
        if user is None:
            raise CommandError(f"no user with email {options['email']}")
        team = Team.objects.select_related("organization").filter(id=options["team"]).first()
        if team is None:
            raise CommandError(f"team {options['team']} does not exist")
        if not user.organization_memberships.filter(organization_id=team.organization_id).exists():
            raise CommandError(f"{user.email} is not a member of team {team.id}'s organization")

        # Both checks run before the mint so a refusal leaves no token behind.
        try:
            app = get_wizard_app()
        except RuntimeError as e:
            raise CommandError(str(e)) from e
        if app.client_id not in settings.WIZARD_GATEWAY_CLIENT_IDS:
            raise CommandError(
                f"wizard app {app.client_id} is not in WIZARD_GATEWAY_CLIENT_IDS; the mint would refuse it as not_wizard_app"
            )
        if GATEWAY_CREDENTIAL_REQUIRED_SCOPE not in (resolve_ceiling(app.ceiling_scopes) or ()):
            raise CommandError(f"wizard app {app.client_id} cannot grant {GATEWAY_CREDENTIAL_REQUIRED_SCOPE}")

        try:
            token = create_wizard_oauth_access_token_for_user(user, team.id)
        except (WizardIdentityBlockedError, RuntimeError) as e:
            raise CommandError(str(e)) from e
        expires = timezone.now() + timedelta(days=days)
        OAuthAccessToken.objects.filter(token=token).update(expires=expires)

        self.stdout.write(
            self.style.SUCCESS(f"wizard CI token for {user.email} on team {team.id}, expires {expires.isoformat()}")
        )
        self.stdout.write(token)
