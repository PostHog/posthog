from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from social_django.models import UserSocialAuth

from posthog.models.user import User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.session.activity import revoke_other_sessions


def reconcile_email_claim_credentials(
    user: User,
    *,
    trusted_password: bool = False,
    trusted_passkey_id: str | None = None,
    trusted_social_auth_id: int | None = None,
    preserve_credentials_reviewed: bool = False,
    preserve_second_factors: bool = False,
) -> User:
    """Reconcile credentials when an email address is claimed."""
    user = User.objects.select_for_update().get(pk=user.pk)
    update_fields: list[str] = []

    if user.credentials_reviewed_at is not None and not preserve_credentials_reviewed:
        user.credentials_reviewed_at = None
        update_fields.append("credentials_reviewed_at")

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
    if not preserve_second_factors:
        TOTPDevice.objects.filter(user=user).delete()
        StaticDevice.objects.filter(user=user).delete()

    if update_fields:
        user.save(update_fields=update_fields)

    revoke_other_sessions(user, keep_session_key=None)
    return user
