"""Offline OIDC token minting for internal ops API tests.

Tokens are signed with a module-level RSA keypair; ``OidcAuthTestMixin`` patches the
JWKS lookup in internal_auth so they verify without any network access.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.conf import settings

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def mint_oidc_token(
    email: str = "ops@posthog.com",
    *,
    audience: str | None = None,
    issuer: str | None = None,
    expiry_delta: timedelta = timedelta(minutes=5),
    email_verified: bool = True,
    **extra_claims: Any,
) -> str:
    return jwt.encode(
        {
            "aud": audience or settings.DATA_MODELING_OPS_OIDC_AUDIENCES[0],
            "iss": issuer or settings.DATA_MODELING_OPS_OIDC_ISSUER,
            "exp": datetime.now(tz=UTC) + expiry_delta,
            "email": email,
            "email_verified": email_verified,
            **extra_claims,
        },
        _PRIVATE_KEY,
        algorithm="RS256",
    )


class OidcAuthTestMixin:
    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        patcher = patch(
            "products.data_modeling.backend.presentation.internal_auth._jwks_client",
            return_value=SimpleNamespace(
                get_signing_key_from_jwt=lambda token: SimpleNamespace(key=_PRIVATE_KEY.public_key())
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]
