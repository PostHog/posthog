import secrets
import string
from django.db import models

from posthog.models.utils import UUIDModel


def _random_character(length: int) -> str:
    return secrets.choice(string.ascii_uppercase + string.digits)


def generate_referral_code():
    """By default referal codes are 16 characters in 4 groups split by dashes."""

    return "-".join("".join(_random_character(4) for _ in range(4)) for _ in range(4))


class ReferralProgramReferrer(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_id", "referral_program"], name="unique user_id for program referrer")
        ]

    user_id: models.CharField = models.CharField(max_length=128)
    code: models.TextField = models.TextField(max_length=128, default=generate_referral_code)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    referral_program: models.ForeignKey = models.ForeignKey(
        "ReferralProgram",
        on_delete=models.CASCADE,
        related_name="referrer",
        related_query_name="referrers",
    )
    max_redemption_count: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)
