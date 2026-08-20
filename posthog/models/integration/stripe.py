"""Stripe App integration: writing PostHog OAuth secrets into Stripe's Secret Store."""

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stripe import StripeClient

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.user import User
from posthog.models.utils import generate_random_oauth_access_token, generate_random_oauth_refresh_token
from posthog.utils import get_instance_region

from . import model, oauth

logger = structlog.get_logger(__name__)


class StripeIntegration:
    integration: model.Integration

    # Every endpoint services/stripe-app/src/posthog/client.ts calls, and nothing else.
    # This token is readable by every member of the customer's Stripe account, so anything
    # granted here is granted to all of them. Read-only by design; do not add a write scope.
    SCOPES: str = " ".join(
        [
            "customer_journey:read",
            "experiment:read",
            "feature_flag:read",
            "insight:read",
            "query:read",
        ]
    )

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "stripe":
            raise ValueError(f"Expected stripe integration, got {integration.kind}")
        self.integration = integration

    def _stripe_client(self) -> "StripeClient | None":
        # Returns None when the required env vars are missing so callers can skip Stripe
        # API calls without raising past their per-secret error handling.
        from stripe import StripeClient  # noqa: PLC0415

        try:
            oauth_config = oauth.OauthIntegration.oauth_config_for_kind("stripe")
        except NotImplementedError as e:
            capture_exception(
                e,
                {
                    "stripe_user_id": self.integration.integration_id,
                },
            )
            return None
        return StripeClient(oauth_config.client_secret)

    def write_posthog_secrets(self, team_id: int, created_by: "User") -> None:
        """Write PostHog OAuth tokens to Stripe's Secret Store so the Stripe App can call PostHog APIs."""

        oauth_app = self._get_posthog_oauth_app()
        if not oauth_app:
            logger.warning("PostHog OAuth app not found, cannot write secrets to Stripe")
            return

        access_token_value = generate_random_oauth_access_token(None)
        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            token=access_token_value,
            user=created_by,
            expires=timezone.now() + timedelta(days=14),
            scope=self.SCOPES,
            scoped_teams=[team_id],
        )

        refresh_token_value = generate_random_oauth_refresh_token(None)
        OAuthRefreshToken.objects.create(
            application=oauth_app,
            token=refresh_token_value,
            user=created_by,
            access_token=access_token,
            scoped_teams=[team_id],
        )

        stripe_user_id = self.integration.integration_id
        if not stripe_user_id:
            raise ValueError("Missing stripe_user_id on integration")

        region = get_instance_region() or "us"

        secrets = {
            "posthog_region": region.lower(),
            "posthog_access_token": access_token_value,
            "posthog_refresh_token": refresh_token_value,
            "posthog_project_id": str(team_id),
            "posthog_oauth_client_id": oauth_app.client_id,
        }

        client = self._stripe_client()
        if client is None:
            return

        for name, payload in secrets.items():
            try:
                client.apps.secrets.create(
                    params={
                        "scope": {"type": "account"},
                        "name": name,
                        "payload": payload,
                    },
                    options={"stripe_account": stripe_user_id},
                )
            except Exception as e:
                capture_exception(
                    e,
                    {
                        "secret_name": name,
                        "stripe_user_id": stripe_user_id,
                    },
                )

    def clear_posthog_secrets(self) -> None:
        """Best-effort clear of PostHog secrets from Stripe and revoke local OAuth tokens."""
        stripe_user_id = self.integration.integration_id
        if not stripe_user_id:
            raise ValueError("Missing stripe_user_id on integration")

        client = self._stripe_client()
        if client is None:
            self._destroy_posthog_oauth_tokens()
            return

        for name in (
            "posthog_region",
            "posthog_access_token",
            "posthog_refresh_token",
            "posthog_project_id",
            "posthog_oauth_client_id",
        ):
            try:
                client.apps.secrets.delete_where(
                    params={
                        "scope": {"type": "account"},
                        "name": name,
                    },
                    options={"stripe_account": stripe_user_id},
                )
            except Exception as e:
                capture_exception(
                    e,
                    {
                        "secret_name": name,
                        "stripe_user_id": stripe_user_id,
                    },
                )

        self._destroy_posthog_oauth_tokens()

    def _destroy_posthog_oauth_tokens(self) -> None:
        """Delete the local OAuth access and refresh tokens created for this Stripe integration."""
        oauth_app = self._get_posthog_oauth_app()
        if not oauth_app:
            return

        team_id = self.integration.team_id
        access_tokens = OAuthAccessToken.objects.filter(
            application=oauth_app,
            scoped_teams__contains=[team_id],
        )
        # Delete refresh tokens first since their FK to access_token is SET_NULL
        OAuthRefreshToken.objects.filter(access_token__in=access_tokens).delete()
        access_tokens.delete()

    def _get_posthog_oauth_app(self):
        if settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID:
            return OAuthApplication.objects.filter(client_id=settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID).first()

        return None
