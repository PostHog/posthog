"""The access token PostHog mints for the organization billing API.

An RS256 `at+jwt` (RFC 9068) signed with the OIDC key, with billing as the audience. Billing
verifies it through PostHog's JWKS. PostHog mints it only on the server, in this module. The
ID-JAG token endpoint refuses billing as a resource (posthog.api.id_jag.get_allowed_resources),
so a client has no way to obtain one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.conf import settings

import jwt
from rest_framework.exceptions import NotAuthenticated

from posthog.api.id_jag import sign_access_token
from posthog.models import Organization

from ee.billing.grants import EffectiveBillingGrants
from ee.models import License

BILLING_TOKEN_CLIENT_ID = "posthog"


LICENSE_ASSERTION_ALGORITHM = "HS256"


def billing_audience() -> str:
    return (getattr(settings, "BILLING_SERVICE_URL", "") or "").rstrip("/")


def build_billing_access_token_payload(
    organization: Organization,
    grants: EffectiveBillingGrants,
    license: Optional[License],
    *,
    act: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if not organization or not license:
        raise NotAuthenticated()
    now = datetime.now(tz=UTC)
    ttl = timedelta(seconds=settings.BILLING_ACCESS_TOKEN_TTL_SECONDS)
    issuer = (settings.SITE_URL or "").rstrip("/")
    audience = billing_audience()
    license_id, _, license_secret = license.key.partition("::")
    jti = str(uuid.uuid4())
    issued_at = int(now.timestamp())
    expires_at = int((now + ttl).timestamp())
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": grants.sub,
        "aud": audience,
        "client_id": BILLING_TOKEN_CLIENT_ID,
        "scope": " ".join(grants.scope),
        "roles": list(grants.roles),
        "entitlements": list(grants.entitlements),
        "org_id": str(organization.id),
        "organization_name": organization.name,
        "projects": list(grants.projects) if grants.projects is not None else None,
        "license_id": license_id,
        "jti": jti,
        "iat": issued_at,
        "exp": expires_at,
        # Proof that whoever minted this holds the license's secret, not merely that they are an
        # allowed issuer. Billing verifies it against the license it resolves, and the jti ties it
        # to this token so it cannot be lifted onto another one.
        "license_assertion": jwt.encode(
            {
                "iss": issuer,
                "sub": license_id,
                "aud": audience,
                "org_id": str(organization.id),
                "jti": jti,
                "iat": issued_at,
                "exp": expires_at,
            },
            license_secret,
            algorithm=LICENSE_ASSERTION_ALGORITHM,
        ),
    }
    if grants.distinct_id:
        # The analytics identity, for attributing what billing captures back to the acting user.
        # Absent when the user has none; `sub` is what identifies the principal.
        payload["distinct_id"] = grants.distinct_id
    if act:
        payload["act"] = act
    return payload


def mint_billing_access_token(
    organization: Organization,
    grants: EffectiveBillingGrants,
    license: Optional[License],
    *,
    act: Optional[dict[str, Any]] = None,
) -> str:
    return sign_access_token(build_billing_access_token_payload(organization, grants, license, act=act))
