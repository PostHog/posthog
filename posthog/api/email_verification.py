import posthoganalytics
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework import exceptions
from sentry_sdk import capture_exception

from posthog.models.user import User
from posthog.tasks.email import send_email_verification

VERIFICATION_DISABLED_FLAG = "email-verification-disabled"


def is_email_verification_disabled(user: User) -> bool:
    # using disabled here so that the default state (if no flag exists) is that verification defaults to ON.
    return user.organization is not None and posthoganalytics.feature_enabled(
        VERIFICATION_DISABLED_FLAG,
        user.organization.id,
        groups={"organization": str(user.organization.id)},
        group_properties={"organization": {"id": str(user.organization.id)}},
    )


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user: AbstractBaseUser, timestamp):
        # Due to type differences between the user model and the token generator, we need to
        # re-fetch the user from the database to get the correct type.
        usable_user: User = User.objects.get(pk=user.pk)
        return f"{usable_user.pk}{usable_user.email}{usable_user.pending_email}{timestamp}"


email_verification_token_generator = EmailVerificationTokenGenerator()


class EmailVerifier:
    @staticmethod
    def create_token_and_send_email_verification(user: User) -> None:
        token = email_verification_token_generator.make_token(user)
        try:
            send_email_verification(user.pk, token)
        except Exception as e:
            capture_exception(Exception(f"Verification email failed: {e}"))
            raise exceptions.APIException(
                detail="Could not send email verification email. Please try again by logging in with your email and password."
            )

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        return email_verification_token_generator.check_token(user, token)
