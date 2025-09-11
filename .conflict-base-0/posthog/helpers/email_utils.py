"""
Provides utilities for handling email addresses with case-insensitive behavior
while maintaining backwards compatibility with existing data that may have mixed casing.
"""

import logging
from typing import TYPE_CHECKING, Optional

from django.core.exceptions import MultipleObjectsReturned
from django.db.models import QuerySet

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models.user import User

logger = logging.getLogger(__name__)


class EmailNormalizer:
    @staticmethod
    def normalize(email: str) -> str:
        if not email:
            return email

        return email.lower()


class EmailLookupHandler:
    @staticmethod
    def get_user_by_email(email: str, is_active: Optional[bool] = True) -> Optional["User"]:
        """
        Get user by email with backwards compatibility.
        First tries exact match (for existing users), then case-insensitive fallback.

        Handles the edge case where multiple users exist with case variations of the same email
        (e.g., test@email.com, Test@email.com, TEST@email.com) by:
        1. Preferring exact case match if it exists
        2. Returning the first case-insensitive match deterministically if no exact match
        """
        from posthog.models.user import User

        queryset = User.objects.filter(is_active=is_active) if is_active else User.objects.all()

        # First try: exact match (preserves existing behavior)
        try:
            return queryset.get(email=email)
        except User.DoesNotExist:
            pass

        # Second try: case-insensitive match
        try:
            return queryset.get(email__iexact=email)
        except User.DoesNotExist:
            return None
        except MultipleObjectsReturned:
            # Handle multiple case variations of the same email
            return EmailMultiRecordHandler.handle_multiple_users(
                queryset.filter(email__iexact=email), email, "user_lookup"
            )


class EmailMultiRecordHandler:
    """
    Utility class for handling cases where multiple records exist with case variations of the same email.
    Provides deterministic behavior and comprehensive logging for monitoring and cleanup.
    """

    @staticmethod
    def handle_multiple_users(queryset: QuerySet, email: str, context: str) -> Optional["User"]:
        """
        Handle multiple user records with case variations of the same email.

        Returns:
            Last logged in user deterministically
        """
        case_insensitive_matches = queryset.order_by("-last_login")
        user_count = case_insensitive_matches.count()
        last_logged_in_user = case_insensitive_matches.first()

        if user_count > 1:
            email_variations = list(case_insensitive_matches.values_list("email", flat=True))
            last_logged_in_user_id = last_logged_in_user.id if last_logged_in_user else None

            posthoganalytics.capture(
                "multiple users with email case variations",
                properties={
                    "email": email,
                    "user_count": user_count,
                    "email_variations": email_variations,
                    "last_logged_in_user_id": last_logged_in_user_id,
                },
            )

            logger.warning(
                f"Multiple users with case variations of email '{email}' during {context}. "
                f"Found {user_count} variations: {email_variations}. "
                f"Returning last logged in user (ID: {last_logged_in_user_id})"
            )

        return last_logged_in_user


class EmailValidationHelper:
    @staticmethod
    def user_exists(email: str) -> bool:
        return EmailLookupHandler.get_user_by_email(email) is not None
