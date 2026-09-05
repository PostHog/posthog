"""The access token PostHog mints for the public billing API.

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

from rest_framework.exceptions import NotAuthenticated

from posthog.api.id_jag import sign_access_token
from posthog.models import Organization

from ee.billing.grants import EffectiveBillingGrants
from ee.models import License

BILLING_TOKEN_CLIENT_ID = "posthog"


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
    payload: dict[str, Any] = {
        "iss": (settings.SITE_URL or "").rstrip("/"),
        "sub": grants.sub,
        "aud": billing_audience(),
        "client_id": BILLING_TOKEN_CLIENT_ID,
        "scope": " ".join(grants.scope),
        "roles": list(grants.roles),
        "entitlements": list(grants.entitlements),
        "org_id": str(organization.id),
        "organization_name": organization.name,
        "projects": list(grants.projects) if grants.projects is not None else None,
        "license_id": license.key.split("::")[0],
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
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
