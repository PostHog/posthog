from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator

from rest_framework import exceptions

from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.tasks.email import send_email_verification

VERIFICATION_DISABLED_FLAG = "email-verification-disabled"


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


class EmailVerifier:
    @staticmethod
    def create_token_and_send_email_verification(user: User, next_url: str | None = None) -> None:
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
