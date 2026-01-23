from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

import structlog

from posthog.models.user import User

logger = structlog.get_logger(__name__)


class TwoFactorResetTokenGenerator(PasswordResetTokenGenerator):
    """
    Token generator for 2FA reset requests initiated by admins.
    Tokens are valid for 1 hour and become invalid after the user's 2FA settings change.
    """

    def check_token(self, user, token):
        """Override to use 1-hour timeout."""
        if not (user and token):
            logger.warning(
                "2FA reset token check failed: missing user or token",
                user_id=getattr(user, "pk", None),
                has_token=bool(token),
            )
            return False

        try:
            ts_b36, _ = token.split("-")
            ts = base36_to_int(ts_b36)
        except ValueError:
            logger.warning(
                "2FA reset token check failed: malformed token",
                user_id=user.pk,
            )
            return False

        # Validate token signature
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
                break
        else:
            logger.warning(
                "2FA reset token check failed: signature mismatch",
                user_id=user.pk,
            )
            return False

        # Check 1-hour timeout (3600 seconds)
        token_age_seconds = self._num_seconds(self._now()) - ts
        if token_age_seconds > 3600:
            logger.warning(
                "2FA reset token check failed: token expired",
                user_id=user.pk,
                token_age_seconds=token_age_seconds,
                max_age_seconds=3600,
            )
            return False

        logger.info(
            "2FA reset token check successful",
            user_id=user.pk,
            token_age_seconds=token_age_seconds,
        )
        return True

    def _make_hash_value(self, user: AbstractBaseUser, timestamp: int) -> str:
        """
        Include requested_2fa_reset_at and 2FA-related state to invalidate tokens after:
        - A new reset is requested
        - The user's 2FA settings change
        - The user's password changes
        """
        usable_user: User = User.objects.get(pk=user.pk)
        # Include requested_2fa_reset_at so that requesting a new reset invalidates old tokens
        reset_timestamp = (
            ""
            if usable_user.requested_2fa_reset_at is None
            else usable_user.requested_2fa_reset_at.replace(microsecond=0, tzinfo=None)
        )
        # Include passkeys_enabled_for_2fa so that changing 2FA settings invalidates tokens
        return f"{usable_user.pk}{usable_user.email}{usable_user.password}{usable_user.passkeys_enabled_for_2fa}{reset_timestamp}{timestamp}"


two_factor_reset_token_generator = TwoFactorResetTokenGenerator()


class TwoFactorResetVerifier:
    @staticmethod
    def create_token(user: User) -> str:
        """Generate a token for 2FA reset."""
        return two_factor_reset_token_generator.make_token(user)

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        """Verify a 2FA reset token."""
        return two_factor_reset_token_generator.check_token(user, token)
