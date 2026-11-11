"""Client-secret signing for the Apple Ads service provider OAuth flow.

Apple issues no static client secret. A service provider registers a public key in Apple Ads and
signs a short-lived ES256 JWT with the matching private key for every call to Apple's token
endpoint, presenting it as `client_secret`. The claims are fixed by Apple: `iss` is the team id,
`sub` is the client id, `aud` is Apple ID, and `kid` in the header is the key id.
"""

import time

import jwt

from posthog.credentials_service.callers import CredentialsCaller
from posthog.credentials_service.settings_fallback import get_many_or_settings

from .common import OauthClientCredentials

APPLE_OAUTH_AUDIENCE = "https://appleid.apple.com"

# Apple accepts a client secret of up to 180 days. A short life is enough here because one is
# signed per token request, and it keeps a leaked assertion near-worthless.
CLIENT_SECRET_TTL_SECONDS = 30 * 60

SERVICE_PROVIDER_CLIENT_ID_KEY = "APPLE_ADS_APP_CLIENT_ID"
SERVICE_PROVIDER_TEAM_ID_KEY = "APPLE_ADS_APP_TEAM_ID"
SERVICE_PROVIDER_KEY_ID_KEY = "APPLE_ADS_APP_KEY_ID"
SERVICE_PROVIDER_PRIVATE_KEY_KEY = "APPLE_ADS_APP_PRIVATE_KEY"


class AppleAdsOauthNotConfigured(Exception):
    pass


def normalize_private_key(private_key: str) -> str:
    """Accept a PEM supplied with literal ``\\n`` escapes as well as real newlines."""
    return private_key.replace("\\n", "\n").strip()


def build_client_secret(
    *,
    client_id: str,
    team_id: str,
    key_id: str,
    private_key: str,
    issued_at: int | None = None,
) -> str:
    now = int(issued_at if issued_at is not None else time.time())
    return jwt.encode(
        {
            "iss": team_id,
            "iat": now,
            "exp": now + CLIENT_SECRET_TTL_SECONDS,
            "aud": APPLE_OAUTH_AUDIENCE,
            "sub": client_id,
        },
        normalize_private_key(private_key),
        algorithm="ES256",
        headers={"alg": "ES256", "kid": key_id},
    )


def service_provider_client_credentials() -> OauthClientCredentials:
    """The client id and a freshly signed client secret for PostHog's own service provider registration."""
    values = get_many_or_settings(
        [
            SERVICE_PROVIDER_CLIENT_ID_KEY,
            SERVICE_PROVIDER_TEAM_ID_KEY,
            SERVICE_PROVIDER_KEY_ID_KEY,
            SERVICE_PROVIDER_PRIVATE_KEY_KEY,
        ],
        CredentialsCaller.INTEGRATIONS,
    )
    if not all(values.values()):
        raise AppleAdsOauthNotConfigured("Apple Ads service provider app not configured")

    client_id = values[SERVICE_PROVIDER_CLIENT_ID_KEY]
    return OauthClientCredentials(
        client_id=client_id,
        client_secret=build_client_secret(
            client_id=client_id,
            team_id=values[SERVICE_PROVIDER_TEAM_ID_KEY],
            key_id=values[SERVICE_PROVIDER_KEY_ID_KEY],
            private_key=values[SERVICE_PROVIDER_PRIVATE_KEY_KEY],
        ),
    )
