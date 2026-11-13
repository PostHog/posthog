import time

from django.conf import settings

from posthog.api.id_jag import sign_access_token
from posthog.constants import AvailableFeature
from posthog.models import Organization, User


def id_jag_access_token(user: User, organization: Organization, scope: str) -> str:
    """An access token as the ID-JAG token endpoint mints it, for `user` in `organization`.

    Turns on XAA for the organization too, because the authenticator refuses ID-JAG tokens
    from an organization without it.
    """
    organization.available_product_features = [
        *(organization.available_product_features or []),
        {"key": AvailableFeature.XAA_AUTHENTICATION, "name": "XAA Authentication"},
    ]
    organization.save()

    site_url = settings.SITE_URL.rstrip("/")
    now = int(time.time())
    return sign_access_token(
        {
            "iss": site_url,
            "aud": site_url,
            "sub": f"example.com:{user.email}",
            "user_uuid": str(user.uuid),
            "client_id": "id-jag-test-client",
            "scope": scope,
            "org_id": str(organization.id),
            "iat": now,
            "exp": now + 300,
        }
    )
