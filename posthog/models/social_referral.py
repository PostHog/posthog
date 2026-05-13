from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDModel


class SocialReferral(UUIDModel):
    """
    Referral share link: who created it (org + user) plus JSON keyed by invited organization id (uuid string)
    tracking whether their first captured event landed.
    """

    referee_state = models.JSONField(
        default=dict,
        blank=True,
        help_text='Per-invited-org map: `{ "<organization_uuid>": { "first_event_sent": boolean } }`.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="social_referrals",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="User who generated this referral link.",
    )

    class Meta:
        db_table = "posthog_social_referral"
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="social_ref_org_created_idx"),
        ]
