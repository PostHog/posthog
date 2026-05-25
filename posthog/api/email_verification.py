from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator

import structlog
import posthoganalytics
from rest_framework import exceptions, status

from posthog.email import is_http_email_service_available
from posthog.exceptions_capture import capture_exception
from posthog.helpers.email_utils import ESPSuppressionReason, check_esp_suppression
from posthog.models.user import User
from posthog.tasks.email import send_email_verification

logger = structlog.get_logger(__name__)

VERIFICATION_DISABLED_FLAG = "email-verification-disabled"


class EmailUndeliverableError(exceptions.APIException):
    """Raised when an outbound verification email is known to be undeliverable.

    Currently the only known case is the ESP (Customer.io) suppression list:
    bounces, spam complaints, and manual unsubscribes land here, and the ESP
    will silently drop subsequent sends. Surfacing this as a distinct error
    code lets the verify-email UI tell the user to contact support instead of
    showing an infinitely-retriable success state.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = (
        "We couldn't deliver a verification email to this address. Please contact support to continue."
    )
    default_code = "email_undeliverable"


def is_email_verification_disabled(user: User) -> bool:
    # using disabled here so that the default state (if no flag exists) is that verification defaults to ON.
    return user.organization is not None and posthoganalytics.feature_enabled(
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


def _check_recipient_deliverable(user: User) -> None:
    """Block the send when the recipient is on the ESP suppression list.

    Only meaningful when Customer.io is the configured sender — the suppression
    list lives there, and SMTP fallback can't be checked. API-failure fallbacks
    return ``is_suppressed=True`` too (so login flows aren't blocked when CIO is
    down), so we narrow to the confirmed ``SUPPRESSED`` reason only.
    """
    if not is_http_email_service_available():
        return

    recipient_email = user.pending_email or user.email
    if not recipient_email:
        return

    suppression_result = check_esp_suppression(recipient_email)
    if not suppression_result.is_suppressed or suppression_result.reason != ESPSuppressionReason.SUPPRESSED:
        return

    logger.info(
        "Email verification skipped due to ESP suppression",
        user_id=user.pk,
        cached=suppression_result.from_cache,
    )
    try:
        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event="verification email skipped due to suppression",
            properties={"cached": suppression_result.from_cache},
        )
    except Exception as e:
        logger.warning("Failed to capture verification suppression event", error=str(e))
    raise EmailUndeliverableError()


class EmailVerifier:
    @staticmethod
    def create_token_and_send_email_verification(user: User, next_url: str | None = None) -> None:
        _check_recipient_deliverable(user)
        token = email_verification_token_generator.make_token(user)
        try:
            send_email_verification(user.pk, token, next_url)
        except Exception as e:
            capture_exception(Exception(f"Verification email failed: {e}"))
            raise exceptions.APIException(
                detail="Could not send email verification email. Please try again by logging in with your email and password."
            )

    @staticmethod
    def check_token(user: User, token: str) -> bool:
        return email_verification_token_generator.check_token(user, token)
