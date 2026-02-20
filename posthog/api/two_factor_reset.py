import time
from typing import cast

from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

import structlog
from rest_framework import permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.user import User

logger = structlog.get_logger(__name__)


class TwoFactorResetTokenGenerator(PasswordResetTokenGenerator):
    """
    Token generator for 2FA reset requests initiated by admins.
    Tokens are valid for 24 hours and become invalid after the user's 2FA settings change.
    """

    def check_token(self, user, token):
        """Override to use 24-hour timeout."""
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

        # Check 24-hour timeout (86400 seconds)
        token_age_seconds = self._num_seconds(self._now()) - ts
        if token_age_seconds > 86400:
            logger.warning(
                "2FA reset token check failed: token expired",
                user_id=user.pk,
                token_age_seconds=token_age_seconds,
                max_age_seconds=86400,
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
        return f"{usable_user.pk}:{usable_user.email}:{usable_user.password}:{usable_user.passkeys_enabled_for_2fa}:{reset_timestamp}:{timestamp}"


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


# 2FA Reset ViewSet - for resetting 2FA when a user has lost access to their authenticator
class TwoFactorResetViewSet(viewsets.ViewSet):
    """
    ViewSet for handling 2FA reset flow initiated by admins.

    The user must be in a "half-authed" state (passed credential auth but not 2FA)
    to access these endpoints. This is verified by checking the session keys
    set during the login flow.

    GET /api/reset_2fa/<user_uuid>/?token=<token> - Validate token and session state
    POST /api/reset_2fa/<user_uuid>/ - Confirm and execute 2FA reset
    """

    permission_classes = (permissions.AllowAny,)

    def _get_half_authed_user(self, request: Request) -> tuple[User | None, str | None]:
        """
        Get the user from either a half-authed session state or a fully authenticated session.
        Returns (user, error_message) tuple.

        Supports two scenarios:
        1. Half-authed: User passed credential auth but not 2FA (normal reset flow)
        2. Fully authed: User already completed 2FA (e.g., admin resetting their own 2FA)

        Note: We use a longer timeout (24 hours) for the 2FA reset flow since
        the reset token itself has a 24-hour expiration. The normal 2FA login
        timeout (10 minutes) is too short for this use case.
        """
        # Check if user is fully authenticated first
        if request.user.is_authenticated:
            # Cast is safe: PostHog only uses User model for authentication
            return cast(User, request.user), None

        # Fall back to half-authed session state
        user_id = request.session.get("user_authenticated_but_no_2fa")
        auth_time = request.session.get("user_authenticated_time")

        if not user_id or auth_time is None:
            return None, "You must log in with your credentials first."

        # Use 24 hour timeout for reset flow (matches the reset token expiration)
        reset_session_timeout = 86400  # 24 hours
        expiration_time = auth_time + reset_session_timeout
        if int(time.time()) > expiration_time:
            return None, "Your login session has expired. Please log in again."

        try:
            user = User.objects.get(pk=user_id)
            return user, None
        except User.DoesNotExist:
            return None, "User not found. Please log in again."

    def retrieve(self, request: Request, user_uuid: str) -> Response:
        """Validate the 2FA reset token and session state."""
        from posthog.api.two_factor_reset import TwoFactorResetVerifier

        token = request.query_params.get("token")

        if not token:
            return Response(
                {"success": False, "error": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify the user is in half-authed state
        session_user, session_error = self._get_half_authed_user(request)
        if session_error or not session_user:
            return Response(
                {
                    "success": False,
                    "error": session_error or "You must log in with your credentials first.",
                    "requires_login": True,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Verify the reset link is for the same user who logged in
        try:
            link_user = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            return Response(
                {"success": False, "error": "This reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if session_user.pk != link_user.pk:
            return Response(
                {"success": False, "error": "This reset link is for a different account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Verify the token
        if not TwoFactorResetVerifier.check_token(link_user, token):
            return Response(
                {"success": False, "error": "This reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"success": True, "token": token})

    def create(self, request: Request, user_uuid: str) -> Response:
        """Execute the 2FA reset after user confirmation."""
        from django_otp.plugins.otp_static.models import StaticDevice
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from posthog.api.two_factor_reset import TwoFactorResetVerifier
        from posthog.tasks.email import send_two_factor_auth_disabled_email

        token = request.data.get("token")

        if not token:
            return Response(
                {"success": False, "error": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify the user is in half-authed state
        session_user, session_error = self._get_half_authed_user(request)
        if session_error or not session_user:
            return Response(
                {
                    "success": False,
                    "error": session_error or "You must log in with your credentials first.",
                    "requires_login": True,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Verify the reset link is for the same user who logged in
        try:
            link_user = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            return Response(
                {"success": False, "error": "This reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if session_user.pk != link_user.pk:
            return Response(
                {"success": False, "error": "This reset link is for a different account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Verify the token
        if not TwoFactorResetVerifier.check_token(link_user, token):
            return Response(
                {"success": False, "error": "This reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delete TOTP devices
        TOTPDevice.objects.filter(user=link_user).delete()

        # Delete static/backup code devices
        StaticDevice.objects.filter(user=link_user).delete()

        # Disable passkey-based 2FA (but keep the passkeys for login)
        link_user.passkeys_enabled_for_2fa = False

        # Clear the reset timestamp so the token can't be reused
        link_user.requested_2fa_reset_at = None
        link_user.save(update_fields=["passkeys_enabled_for_2fa", "requested_2fa_reset_at"])

        # Clear the half-auth session state so user must login fresh
        request.session.pop("user_authenticated_but_no_2fa", None)
        request.session.pop("user_authenticated_time", None)

        # Send notification email
        send_two_factor_auth_disabled_email.delay(link_user.pk)

        return Response({"success": True})
