import time

from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator

import structlog
from rest_framework import exceptions

from posthog.exceptions_capture import capture_exception
from posthog.helpers.two_factor_session import (
    CODE_MAX_ATTEMPTS,
    CODE_TTL_SECONDS,
    code_based_verification_token_generator,
    is_code_based_verification_globally_disabled,
)
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.redis import get_client
from posthog.tasks.email import send_email_verification, send_email_verification_code

logger = structlog.get_logger(__name__)

VERIFICATION_DISABLED_FLAG = "email-verification-disabled"

EMAIL_CODE_STATE_REDIS_KEY_PREFIX = "email_verification_code_state"
EMAIL_CODE_ATTEMPTS_REDIS_KEY_PREFIX = "email_verification_code_attempts"


def is_email_verification_disabled(user: User) -> bool:
    # using disabled here so that the default state (if no flag exists) is that verification defaults to ON.
    return user.organization is not None and feature_enabled_or_false(
        VERIFICATION_DISABLED_FLAG,
        str(user.organization.id),
        groups={"organization": str(user.organization.id)},
        group_properties={"organization": {"id": str(user.organization.id)}},
    )


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user: AbstractBaseUser, timestamp):
        # Due to type differences between the user model and the token generator, we need to
        # re-fetch the user from the database to get the correct type.
        usable_user: User = User.objects.get(pk=user.pk)
        login_timestamp = "" if user.last_login is None else user.last_login.replace(microsecond=0, tzinfo=None)

        return f"{usable_user.pk}{usable_user.email}{usable_user.is_email_verified}{usable_user.pending_email}{login_timestamp}{timestamp}"


email_verification_token_generator = EmailVerificationTokenGenerator()


class EmailVerificationCodeVerifier:
    """Issues and checks the 6-digit code for signup and email-change verification.

    Unlike the login code flow, pending state (issuance time, target address, attempt counter)
    lives in Redis keyed by user id, not in the session. Verification must work after the user
    closes the tab or opens the app in a different browser. The code itself is derived by
    `code_based_verification_token_generator` and never stored.

    The stored target address does for codes what the `pending_email` hash input does for link
    tokens: a code verifies only the address it was issued for. One Redis slot per user means
    a new code always invalidates the previous one.

    The attempt budget is separate from the code. It is not reset by issuing a new code, because
    the resend endpoint is public: a reset there would let a caller alternate resends and guesses
    to brute-force the code. Exceeding the budget refuses checks until it expires, but keeps the
    code alive, so a stranger who knows the user's uuid cannot destroy a live verification.
    """

    @staticmethod
    def _state_key(user_id: int) -> str:
        return f"{EMAIL_CODE_STATE_REDIS_KEY_PREFIX}:{user_id}"

    @staticmethod
    def _attempts_key(user_id: int) -> str:
        return f"{EMAIL_CODE_ATTEMPTS_REDIS_KEY_PREFIX}:{user_id}"

    def send_code(self, user: User, target_email: str | None = None) -> bool:
        """Issue a fresh code and email it to the address it authorizes.

        Returns False when the code was not issued or sent, so the caller can send the
        link email instead."""
        try:
            # Signup verification always proves the account address. Only a verified user's
            # email change targets the staged address; an unverified user's staged change must
            # not let a code sent to the unverified new address verify the account.
            target: str | None = target_email
            if target is None and user.is_email_verified:
                target = user.pending_email
            issued_at = int(time.time())
            code = code_based_verification_token_generator.make_code(user, issued_at)
            # Write the state before the send, so a delivered code can always verify.
            get_client().set(self._state_key(user.pk), f"{issued_at}:{target or ''}", ex=CODE_TTL_SECONDS)
            send_email_verification_code(user.pk, code, target)
            return True
        except Exception as e:
            logger.exception("Email verification code send failed", user_id=user.pk, error=str(e))
            capture_exception(Exception(f"Email verification code send failed: {e}"))
            return False

    def _get_state(self, user: User) -> tuple[int, str] | None:
        """Return (issued_at, target_email) for the pending code. target_email is '' for signup."""
        try:
            raw = get_client().get(self._state_key(user.pk))
            if not raw:
                return None
            text = raw.decode() if isinstance(raw, bytes) else raw
            issued_at_raw, _, target = text.partition(":")
            return int(issued_at_raw), target
        except Exception:
            logger.exception("Failed to read email verification code state", user_id=user.pk)
            return None

    def reserve_attempt(self, user: User) -> int:
        """Count one verification attempt atomically.

        Returns the running total, including this attempt. Returns 0 on Redis failure,
        failing open - the endpoint throttle is the backstop."""
        try:
            client = get_client()
            count = int(client.incr(self._attempts_key(user.pk)))
            if count == 1:
                # Only the first attempt starts the window, so further guesses cannot extend a lockout.
                client.expire(self._attempts_key(user.pk), CODE_TTL_SECONDS)
            return count
        except Exception:
            logger.exception("Failed to reserve email verification code attempt", user_id=user.pk)
            return 0

    def check_code(self, user: User, code: str) -> bool:
        state = self._get_state(user)
        if not state:
            return False
        issued_at, target = state
        # A code verifies only the address it was issued for. Signup codes store '' as the target.
        expected_target = (user.pending_email or "") if user.is_email_verified else ""
        if target != expected_target:
            return False
        return code_based_verification_token_generator.check_code(user, code, issued_at)

    def invalidate(self, user: User) -> None:
        try:
            get_client().delete(self._state_key(user.pk), self._attempts_key(user.pk))
        except Exception:
            logger.exception("Failed to invalidate email verification code", user_id=user.pk)

    def attempts_exceeded(self, attempts: int) -> bool:
        return attempts > CODE_MAX_ATTEMPTS

    def _clear_attempts_for_test(self, user: User) -> None:
        get_client().delete(self._attempts_key(user.pk))


email_verification_code_verifier = EmailVerificationCodeVerifier()


class EmailVerifier:
    @staticmethod
    def use_verification_code(user: User) -> bool:
        """Signup and email-change verification use an emailed code. The code-based-verification
        kill-switch reverts both to the token-link flow."""
        return (not user.is_email_verified or bool(user.pending_email)) and (
            not is_code_based_verification_globally_disabled()
        )

    @staticmethod
    def create_token_and_send_email_verification(user: User, next_url: str | None = None) -> None:
        if EmailVerifier.use_verification_code(user) and email_verification_code_verifier.send_code(user):
            return
        token = email_verification_token_generator.make_token(user)
        EmailVerifier.send_verification_email(user, token, next_url=next_url)

    @staticmethod
    def send_verification_email(
        user: User, token: str, next_url: str | None = None, target_email: str | None = None
    ) -> None:
        # `target_email` pins the recipient to the address the token authorizes; callers with a
        # stable email leave it None and the recipient falls back to the user's pending_email.
        try:
            send_email_verification(user.pk, token, next_url, target_email)
        except Exception as e:
            capture_exception(Exception(f"Verification email failed: {e}"))
            raise exceptions.APIException(
                detail="Could not send email verification email. Please try again by logging in with your email and password."
            )

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        return email_verification_token_generator.check_token(user, token)
