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

SIGNUP_CODE_ISSUED_AT_REDIS_KEY_PREFIX = "signup_email_verification_issued_at"
SIGNUP_CODE_ATTEMPTS_REDIS_KEY_PREFIX = "signup_email_verification_attempts"


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


class SignupEmailCodeVerifier:
    """Issues and checks the 6-digit signup verification code.

    Unlike the login code flow, pending state lives in Redis keyed by user id rather than in the
    session: signup verification must survive the user closing the tab or reopening the app in a
    different browser, where no session carries the pending state. The code itself is derived by
    `code_based_verification_token_generator`, so it is never stored; only the issuance time and
    the attempt counter are.
    """

    @staticmethod
    def _issued_at_key(user_id: int) -> str:
        return f"{SIGNUP_CODE_ISSUED_AT_REDIS_KEY_PREFIX}:{user_id}"

    @staticmethod
    def _attempts_key(user_id: int) -> str:
        return f"{SIGNUP_CODE_ATTEMPTS_REDIS_KEY_PREFIX}:{user_id}"

    def send_code(self, user: User) -> bool:
        """Issue a fresh code and email it. Returns False when the code could not be issued or
        sent, so the caller can fall back to the link email instead of leaving the user stuck."""
        try:
            issued_at = int(time.time())
            code = code_based_verification_token_generator.make_code(user, issued_at)
            # State before send: an email whose code can never verify is worse than no email.
            client = get_client()
            client.set(self._issued_at_key(user.pk), issued_at, ex=CODE_TTL_SECONDS)
            client.delete(self._attempts_key(user.pk))
            send_email_verification_code(user.pk, code)
            return True
        except Exception as e:
            logger.exception("Signup verification code send failed", user_id=user.pk, error=str(e))
            capture_exception(Exception(f"Signup verification code send failed: {e}"))
            return False

    def get_issued_at(self, user: User) -> int | None:
        try:
            raw = get_client().get(self._issued_at_key(user.pk))
            return int(raw) if raw else None
        except Exception:
            logger.exception("Failed to read signup verification code state", user_id=user.pk)
            return None

    def reserve_attempt(self, user: User) -> int:
        """Atomically count a verification attempt. Returns the running total including this one;
        0 on Redis failure (fail open — the endpoint throttle is the backstop)."""
        try:
            client = get_client()
            count = int(client.incr(self._attempts_key(user.pk)))
            client.expire(self._attempts_key(user.pk), CODE_TTL_SECONDS)
            return count
        except Exception:
            logger.exception("Failed to reserve signup verification code attempt", user_id=user.pk)
            return 0

    def check_code(self, user: User, code: str) -> bool:
        issued_at = self.get_issued_at(user)
        if not issued_at:
            return False
        return code_based_verification_token_generator.check_code(user, code, issued_at)

    def invalidate(self, user: User) -> None:
        try:
            get_client().delete(self._issued_at_key(user.pk), self._attempts_key(user.pk))
        except Exception:
            logger.exception("Failed to invalidate signup verification code", user_id=user.pk)

    def attempts_exceeded(self, attempts: int) -> bool:
        return attempts > CODE_MAX_ATTEMPTS


signup_email_code_verifier = SignupEmailCodeVerifier()


class EmailVerifier:
    @staticmethod
    def use_verification_code(user: User) -> bool:
        """Signup verification uses an emailed code; email changes keep the token link, and the
        code-based-verification kill-switch reverts signups to the link flow too."""
        return (
            not user.is_email_verified and not user.pending_email and not is_code_based_verification_globally_disabled()
        )

    @staticmethod
    def create_token_and_send_email_verification(user: User, next_url: str | None = None) -> None:
        if EmailVerifier.use_verification_code(user) and signup_email_code_verifier.send_code(user):
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
