from enum import StrEnum

from django.utils import timezone

from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.constants import AvailableFeature
from posthog.models import Organization, User
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.webauthn_credential import WebauthnCredential

# COSE identifier of ES256, the algorithm passkeys sign with by default.
ES256_COSE_ALGORITHM = -7

# The enforced provider counts only when the instance has it configured, so tests that use SSO_ENFORCED apply these.
GOOGLE_SSO_SETTINGS = {
    "CLOUD_DEPLOYMENT": "US",
    "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY": "synthetic-client",
    "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET": "synthetic-secret",
}


class NormalLoginRequirement(StrEnum):
    TOTP = "totp"
    PASSKEY = "passkey"
    SSO_ENFORCED = "sso_enforced"


def require_normal_login(user: User, organization: Organization, requirement: NormalLoginRequirement) -> None:
    """Give `user` the account setup that makes a login without the login page refuse them."""
    if requirement == NormalLoginRequirement.TOTP:
        TOTPDevice.objects.create(user=user, name="default", confirmed=True)

    elif requirement == NormalLoginRequirement.PASSKEY:
        user.passkeys_enabled_for_2fa = True
        user.save(update_fields=["passkeys_enabled_for_2fa"])
        WebauthnCredential.objects.create(
            user=user,
            credential_id=b"synthetic-credential",
            public_key=b"synthetic-public-key",
            algorithm=ES256_COSE_ALGORITHM,
            verified=True,
        )

    elif requirement == NormalLoginRequirement.SSO_ENFORCED:
        organization.available_product_features = [
            *(organization.available_product_features or []),
            {"key": AvailableFeature.SSO_ENFORCEMENT, "name": "SSO enforcement"},
        ]
        organization.save(update_fields=["available_product_features"])
        OrganizationDomain.objects.create(
            organization=organization,
            domain=user.email.split("@")[1],
            verified_at=timezone.now(),
            sso_enforcement="google-oauth2",
        )
