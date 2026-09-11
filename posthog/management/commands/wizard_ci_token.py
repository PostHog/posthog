"""
Mint a long-lived wizard-app OAuth token for the wizard CI smoke test.

Usage:
    python manage.py wizard_ci_token --email ci-bot@example.com --team 2
    python manage.py wizard_ci_token --email ci-bot@example.com --team 2 --days 90

The smoke test runs `wizard --ci --api-key <token>`. A personal API key (phx_)
is refused at the gateway-token mint as `invalid_token`, so CI needs a `pha_`
issued under the wizard OAuth app with `llm_gateway:read`, scoped to one team.

Two things bound it. It carries that one scope rather than the wizard app's
whole ceiling, and it expires in 30 days by default, because a credential
holding `llm_gateway:read` authenticates at the AI gateway on its own, where
none of the wizard mint's gates apply: no blocklist recheck, no rollout switch,
no program pin, no mint throttle, no per-run cap. The lifetime is the bound.

--team must be the wizard app's organization root team, which is what the
gateway attributes the app's tokens to; any other team mints a credential it
refuses. Re-running revokes the previous CI token for the same user and team,
so a rotation leaves nothing live behind it. The token is printed once, on the last
line of output, and stored nowhere else: put it straight in the CI secret.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models import OAuthAccessToken, Team, User
from posthog.scopes import resolve_ceiling

# _org_root_team_id is what projection itself resolves an OAuth credential's team
# with, so the pre-mint check reuses it rather than restating the query and
# drifting from it.
from posthog.storage.gateway_credential_cache import GATEWAY_CREDENTIAL_REQUIRED_SCOPE, _org_root_team_id
from posthog.temporal.oauth import WizardIdentityBlockedError, create_wizard_oauth_access_token_for_user, get_wizard_app

logger = structlog.get_logger(__name__)

_DEFAULT_DAYS = 30
_MAX_DAYS = 90


class WizardCiTokenError(Exception):
    """A refusal the command renders as a CommandError."""


@dataclass(frozen=True)
class WizardCiToken:
    token: str
    expires: datetime
    revoked: int
    email: str
    team_id: int


def rotate_wizard_ci_token(*, email: str, team_id: int, days: int) -> WizardCiToken:
    """Mint the CI credential, then revoke the one it replaces.

    Serialized per user: two rotations that overlap would each mint and then
    delete the other's row, leaving CI with nothing live.
    """
    if days < 1 or days > _MAX_DAYS:
        raise WizardCiTokenError(f"--days must be between 1 and {_MAX_DAYS}")

    try:
        app = get_wizard_app()
    except RuntimeError as e:
        raise WizardCiTokenError(str(e)) from e
    if app.client_id not in settings.WIZARD_GATEWAY_CLIENT_IDS:
        raise WizardCiTokenError(
            f"wizard app {app.client_id} is not in WIZARD_GATEWAY_CLIENT_IDS; the mint would refuse it as not_wizard_app"
        )
    if GATEWAY_CREDENTIAL_REQUIRED_SCOPE not in (resolve_ceiling(app.ceiling_scopes) or ()):
        raise WizardCiTokenError(f"wizard app {app.client_id} cannot grant {GATEWAY_CREDENTIAL_REQUIRED_SCOPE}")

    team = Team.objects.select_related("organization").filter(id=team_id).first()
    if team is None:
        raise WizardCiTokenError(f"team {team_id} does not exist")

    # The gateway attributes an OAuth credential to its application's organization
    # root, not to scoped_teams, and then fails the token closed when the two
    # disagree. Checked here so a mismatch is a refusal rather than a printed
    # token the gateway rejects.
    attributed = _org_root_team_id(app.organization_id)
    if attributed is None:
        raise WizardCiTokenError(
            f"wizard app {app.client_id} has no single organization root team, so the gateway cannot attribute its tokens"
        )
    if attributed != team.id:
        raise WizardCiTokenError(
            f"team {team.id} is not the wizard app's organization root team ({attributed}); "
            "the gateway would refuse a token scoped to it"
        )

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise WizardCiTokenError(f"no user with email {email}")
    if not user.organization_memberships.filter(organization_id=team.organization_id).exists():
        raise WizardCiTokenError(f"{user.email} is not a member of team {team.id}'s organization")

    with transaction.atomic():
        # Locks this user's row for the transaction, so an overlapping rotation
        # waits rather than racing the mint against the revoke.
        User.objects.select_for_update().get(pk=user.pk)

        try:
            token = create_wizard_oauth_access_token_for_user(user, team.id, scopes=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE])
        except (WizardIdentityBlockedError, RuntimeError) as e:
            raise WizardCiTokenError(str(e)) from e

        # save(), not queryset update(): the gateway's credential blob is
        # projected on post_save, which an update() does not fire, so the
        # gateway would keep serving the mint helper's six-hour expiry.
        row = OAuthAccessToken.objects.get(token=token)
        expires = timezone.now() + timedelta(days=days)
        row.expires = expires
        row.save(update_fields=["expires"])

        # After the mint, so a refusal leaves the working credential in place.
        superseded = (
            OAuthAccessToken.objects.filter(
                user=user, application=app, scoped_teams=[team.id], scope=GATEWAY_CREDENTIAL_REQUIRED_SCOPE
            )
            .exclude(expires__lte=timezone.now())
            .exclude(pk=row.pk)
        )
        revoked = superseded.count()
        superseded.delete()

    logger.info(
        "wizard_ci_token: issued",
        user_uuid=str(user.uuid),
        team_id=team.id,
        scope=GATEWAY_CREDENTIAL_REQUIRED_SCOPE,
        expires=expires.isoformat(),
        revoked_previous=revoked,
    )
    return WizardCiToken(token=token, expires=expires, revoked=revoked, email=user.email, team_id=team.id)


class Command(BaseCommand):
    help = "Mint a long-lived wizard-app OAuth token (pha_) for the wizard CI smoke test."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True, help="the CI bot user's email")
        parser.add_argument("--team", type=int, required=True, help="team id the token is scoped to")
        parser.add_argument("--days", type=int, default=_DEFAULT_DAYS, help=f"lifetime in days (1-{_MAX_DAYS})")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            issued = rotate_wizard_ci_token(email=options["email"], team_id=options["team"], days=options["days"])
        except WizardCiTokenError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(
            self.style.SUCCESS(
                f"wizard CI token for {issued.email} on team {issued.team_id}, "
                f"scope {GATEWAY_CREDENTIAL_REQUIRED_SCOPE}, "
                f"expires {issued.expires.isoformat()}, revoked {issued.revoked} previous"
            )
        )
        self.stdout.write("Store it in the CI secret; it is not recoverable and re-running revokes it.")
        self.stdout.write(issued.token)
