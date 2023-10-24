import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .utils import UUIDModel


def get_email_hash(email: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}_{email}".encode()).hexdigest()


class MessagingRecordManager(models.Manager):
    def get_or_create(self, defaults=None, **kwargs):
        raw_email = kwargs.pop("raw_email", None)

        if raw_email:
            kwargs["email_hash"] = get_email_hash(raw_email)

        return super().get_or_create(defaults, **kwargs)

    def filter(self, *args, **kwargs):
        raw_email = kwargs.pop("raw_email", None)

        if raw_email:
            kwargs["email_hash"] = get_email_hash(raw_email)

        return super().filter(*args, **kwargs)

    def create(self, *args, **kwargs):
        raw_email = kwargs.pop("raw_email", None)

        if raw_email:
            kwargs["email_hash"] = get_email_hash(raw_email)

        return super().create(*args, **kwargs)


class MessagingRecord(UUIDModel):
    objects = MessagingRecordManager()

    email_hash: models.CharField = models.CharField(max_length=1024)
    campaign_key: models.CharField = models.CharField(max_length=128)
    # Numeric indicator for repeat emails of the same campaign key
    campaign_count: models.IntegerField = models.IntegerField(null=True)
    sent_at: models.DateTimeField = models.DateTimeField(null=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (
            "email_hash",
            "campaign_key",
            "campaign_count",
        )  # can only send campaign once to each email for a given count

    def can_be_resent(self, resend_interval: timedelta) -> bool:
        """
        Returns whether an email should be sent based on the sent_at and the resend frequency.
        """
        return self.sent_at and (timezone.now() - self.sent_at) >= resend_interval

    def next_campaign_count(self) -> int:
        return 1 if self.campaign_count is None else self.campaign_count + 1
