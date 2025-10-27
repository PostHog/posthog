from typing import Any

from django.core.cache import cache

import structlog
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from social_core.utils import requests

from ee.api.vercel.types import VercelClaims, VercelUser, VercelUserClaims

VERCEL_JWKS_URL = "https://marketplace.vercel.com/.well-known/jwks.json"
VERCEL_JWKS_CACHE_KEY = "vercel_jwks"
VERCEL_JWKS_CACHE_TIMEOUT = 600

logger = structlog.get_logger(__name__)


def get_vercel_claims(request: Request) -> VercelClaims:
    """
    Auth OIDC token claims are attached to the VercelUser during authentication.
    This narrows the type of the request so we can use the claims.
    """

    if not isinstance(request.user, VercelUser):
        raise AuthenticationFailed("Not authenticated with Vercel")

    return request.user.claims


def expect_vercel_user_claim(request: Request) -> VercelUserClaims:
    claim = get_vercel_claims(request)

    if not isinstance(claim, VercelUserClaims):
        raise AuthenticationFailed("Invalid claim type")

    return claim


def get_vercel_jwks() -> dict[str, Any]:
    jwks = cache.get(VERCEL_JWKS_CACHE_KEY)
    if jwks is None:
        for attempt in range(3):
            try:
                response = requests.get(VERCEL_JWKS_URL, timeout=10)
                response.raise_for_status()
                jwks = response.json()
                cache.set(VERCEL_JWKS_CACHE_KEY, jwks, timeout=VERCEL_JWKS_CACHE_TIMEOUT)
                logger.debug("JWKS fetched successfully")
                break
            except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
                if attempt == 2:
                    logger.exception("JWKS fetch failed after all retries", attempts=3, error=str(e))
                    raise
                logger.warning("JWKS fetch failed, retrying", attempt=attempt + 1, error=str(e))
    return jwks
