import datetime

import structlog
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework import exceptions
from sentry_sdk import capture_exception

from posthog.models.user import User
from posthog.tasks.email import send_password_reset

logger = structlog.get_logger(__name__)


class PHPasswordResetTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user: AbstractBaseUser, timestamp):
        # Due to type differences between the user model and the token generator, we need to
        # re-fetch the user from the database to get the correct type.
        usable_user: User = User.objects.get(pk=user.pk)
        logger.info(
            f"Password reset token for {usable_user.email} requested at {usable_user.requested_password_reset_at}"
        )
        return f"{usable_user.pk}{usable_user.email}{usable_user.requested_password_reset_at}{timestamp}"


password_reset_token_generator = PHPasswordResetTokenGenerator()


class PasswordResetter:
    @staticmethod
    def create_token_and_send_reset_email(user: User) -> None:
        user.requested_password_reset_at = datetime.datetime.now(datetime.timezone.utc)
        user.save()
        token = password_reset_token_generator.make_token(user)
        logger.info(f"Password reset requested for {user.email}")

        try:
            send_password_reset(user.pk, token)
        except Exception as e:
            capture_exception(Exception(f"Verification email failed: {e}"))
            raise exceptions.APIException(
                detail="Could not send email verification email. Please try again by logging in with your email and password."
            )

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        return password_reset_token_generator.check_token(user, token)
