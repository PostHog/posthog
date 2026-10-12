"""Client-secret signing for the Apple Ads service provider OAuth flow.

Apple issues no static client secret. A service provider registers a public key in Apple Ads and
signs a short-lived ES256 JWT with the matching private key for every call to Apple's token
endpoint, presenting it as `client_secret`. The claims are fixed by Apple: `iss` is the team id,
`sub` is the client id, `aud` is Apple ID, and `kid` in the header is the key id.
"""

import time

from django.conf import settings

import jwt

APPLE_OAUTH_AUDIENCE = "https://appleid.apple.com"

# Apple accepts a client secret of up to 180 days. A short life is enough here because one is
# signed per token request, and it keeps a leaked assertion near-worthless. It must outlive the
# OauthConfig cache (5 minutes), which hands the same signed value to every caller in that window.
CLIENT_SECRET_TTL_SECONDS = 30 * 60


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


def service_provider_client_secret() -> str:
    """Sign a client secret for PostHog's own Apple Ads service provider registration."""
    if not all(
        (
            settings.APPLE_ADS_APP_CLIENT_ID,
            settings.APPLE_ADS_APP_TEAM_ID,
            settings.APPLE_ADS_APP_KEY_ID,
            settings.APPLE_ADS_APP_PRIVATE_KEY,
        )
    ):
        raise AppleAdsOauthNotConfigured("Apple Ads service provider app not configured")

    return build_client_secret(
        client_id=settings.APPLE_ADS_APP_CLIENT_ID,
        team_id=settings.APPLE_ADS_APP_TEAM_ID,
        key_id=settings.APPLE_ADS_APP_KEY_ID,
        private_key=settings.APPLE_ADS_APP_PRIVATE_KEY,
    )
