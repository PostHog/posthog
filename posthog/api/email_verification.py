from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator

from posthog.models.user import User
from posthog.tasks.email import send_email_verification


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user: AbstractBaseUser, timestamp):
        user = User(user)
        return f"{user.pk}{user.email}{user.pending_email}{timestamp}"


email_verification_token_generator = EmailVerificationTokenGenerator()


class EmailVerifier:
    @staticmethod
    def create_token_and_send_email_verification(user: User) -> None:
        token = email_verification_token_generator.make_token(user)
        send_email_verification.delay(user.pk, token)

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        return email_verification_token_generator.check_token(user, token)
