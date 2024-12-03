import hashlib

from django.conf import settings
from django.db import models

from .utils import UUIDModel


def get_email_hash(email: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}_{email}".encode()).hexdigest()


class MessagingRecordManager(models.Manager):
    def get_or_create(self, defaults=None, **kwargs):
        raw_email = kwargs.pop("raw_email", None)

        if raw_email:
            kwargs["email_hash"] = get_email_hash(raw_email)

        return super().get_or_create(defaults, **kwargs)


class MessagingRecord(UUIDModel):
    objects = MessagingRecordManager()

    email_hash = models.CharField(max_length=1024)
    campaign_key = models.CharField(max_length=128)
    # Numeric indicator for repeat emails of the same campaign key
    campaign_count = models.IntegerField(null=True)
    sent_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (
            "email_hash",
            "campaign_key",
        )  # can only send campaign once to each email
