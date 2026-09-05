from social_django.models import UserSocialAuth

from posthog.models.oauth import OAuthAccessToken, OAuthGrant, OAuthIDToken, OAuthRefreshToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.webauthn_credential import WebauthnCredential


def reconcile_email_claim_credentials(
    user: User,
    *,
    trusted_password: bool = False,
    trusted_passkey_id: str | None = None,
    trusted_social_auth_id: int | None = None,
) -> None:
    """Keep only credentials proved by the flow that claimed the user's email address."""
    update_fields: list[str] = []

    if not trusted_password:
        user.set_unusable_password()
        update_fields.append("password")

    passkeys = WebauthnCredential.objects.filter(user=user)
    trusted_passkey_exists = bool(
        trusted_passkey_id and passkeys.filter(id=trusted_passkey_id).update(verified=True) == 1
    )
    if trusted_passkey_exists:
        passkeys.exclude(id=trusted_passkey_id).delete()
    else:
        passkeys.delete()
        if user.passkeys_enabled_for_2fa:
            user.passkeys_enabled_for_2fa = False
            update_fields.append("passkeys_enabled_for_2fa")

    social_auth = UserSocialAuth.objects.filter(user=user)
    if trusted_social_auth_id is not None:
        social_auth = social_auth.exclude(id=trusted_social_auth_id)
    social_auth.delete()

    PersonalAPIKey.objects.filter(user=user).delete()
    OAuthGrant.objects.filter(user=user).delete()
    OAuthIDToken.objects.filter(user=user).delete()
    OAuthRefreshToken.objects.filter(user=user).delete()
    OAuthAccessToken.objects.filter(user=user).delete()

    if update_fields:
        user.save(update_fields=update_fields)
