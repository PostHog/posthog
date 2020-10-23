import hashlib
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.db import models

from posthog.models.user import User

from .base import BaseModel

CAMPAIGNS: List[Dict[str, Optional[str]]] = [
    {
        "id": "weekly_report",
        "name": "Weekly report",
        "descrpition": "Receive a snapshot of your data every Monday with details of new and previous usage.",
        "default_opt_in": True,
    }
]


class MessagingRecordManager(models.Manager):
    def get_or_create(self, defaults=None, **kwargs):
        raw_email = kwargs.pop("raw_email", None)

        if raw_email:
            kwargs["email_hash"] = hashlib.sha256(f"{settings.SECRET_KEY}_{raw_email}".encode()).hexdigest()

        return super().get_or_create(defaults, **kwargs)


class MessagingRecord(BaseModel):

    objects = MessagingRecordManager()

    email_hash: models.CharField = models.CharField(max_length=1024)
    campaign_key: models.CharField = models.CharField(
        max_length=128,
    )  # represents a one-off campaign or a specific instance if it's a recurring campaign
    sent_at: models.DateTimeField = models.DateTimeField(null=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("email_hash", "campaign_key")  # can only send campaign once to each email


class MessagingPreference(BaseModel):
    """
    Represents a user's deliberate preference on whether to receive a certain campaign.
    """

    CAMPAIGN_CHOICES: List[Tuple[str, str]] = [(c["id"], c["name"]) for c in CAMPAIGNS]
    STATE_CHOICES: List[Tuple[str, str]] = [
        ("opt_in", "Opted In"),
        ("opt_out", "Opted Out"),
    ]

    user: models.ForeignKey = models.ForeignKey(User, related_name="messaging_preferences", on_delete=models.CASCADE)
    campaign: models.CharField = models.CharField(max_length=32)
    state: models.CharField = models.CharField(max_length=16, choices=STATE_CHOICES)
