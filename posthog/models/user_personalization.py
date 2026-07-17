from django.db import models

from posthog.models.utils import UUIDModel


class UserPersonalization(UUIDModel):
    """
    Per-user appearance/profile preferences. A side table rather than columns
    on posthog_user, which is too hot to ALTER casually.
    """

    # db_constraint=False so CreateModel takes no lock on hot posthog_user;
    # the FK constraint is added NOT VALID + validated in the migration.
    user = models.OneToOneField(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="personalization",
        db_constraint=False,
    )
    avatar_url = models.URLField(
        max_length=800,
        null=True,
        blank=True,
        help_text="Profile picture URL, shown across PostHog apps in place of the Gravatar/initials fallback.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
