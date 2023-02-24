from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator

from posthog.models.user import User
from posthog.tasks.email import send_email_verification


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
        send_email_verification.delay(user.pk, token)

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        return email_verification_token_generator.check_token(user, token)
