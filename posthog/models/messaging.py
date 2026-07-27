import hashlib

from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDTModel


def _hash_email(email: str, salt: str) -> str:
    if not salt:
        raise ValueError("Refusing to hash an email with an empty MessagingRecord salt")
    return hashlib.sha256(f"{salt}_{email}".encode()).hexdigest()


def get_email_hash(email: str) -> str:
    """Hash to store when *writing* a MessagingRecord — always the primary salt."""
    return _hash_email(email, settings.MESSAGING_HASH_SALT)


def get_email_hashes(email: str) -> list[str]:
    """All hashes to match when *reading* — primary salt plus any rotation fallbacks.

    Lets us rotate MESSAGING_HASH_SALT without re-sending already-sent campaigns: new
    records are written under the primary salt, but dedup lookups still find records
    written under a previous salt listed in MESSAGING_HASH_SALT_FALLBACKS.
    """
    salts = {settings.MESSAGING_HASH_SALT, *settings.MESSAGING_HASH_SALT_FALLBACKS}
    return [_hash_email(email, salt) for salt in salts if salt]


class MessagingRecordManager(models.Manager):
    def get_or_create(self, defaults=None, **kwargs):
        raw_email = kwargs.pop("raw_email", None)
        if raw_email is None:
            return super().get_or_create(defaults, **kwargs)

        # Read across the primary salt and any rotation fallbacks (via the filter
        # override) so we don't re-send a campaign already recorded under a previous
        # salt; write under the primary salt only.
        existing = self.filter(raw_email=raw_email, **kwargs).first()
        if existing is not None:
            return existing, False

        kwargs["email_hash"] = get_email_hash(raw_email)
        return super().get_or_create(defaults, **kwargs)

    async def aget_or_create(self, defaults=None, **kwargs):
        raw_email = kwargs.pop("raw_email", None)
        if raw_email is None:
            return await super().aget_or_create(defaults, **kwargs)

        existing = await self.filter(raw_email=raw_email, **kwargs).afirst()
        if existing is not None:
            return existing, False

        kwargs["email_hash"] = get_email_hash(raw_email)
        return await super().aget_or_create(defaults, **kwargs)

    def filter(self, *args, **kwargs):
        # A raw_email maps to multiple hashes across salt rotations, so we only remap it
        # on filter() — never get(), which would raise MultipleObjectsReturned if both a
        # pre- and post-rotation record exist. Callers needing one row use
        # filter(raw_email=...).first()/.exists().
        raw_email = kwargs.pop("raw_email", None)
        if raw_email is not None:
            kwargs["email_hash__in"] = get_email_hashes(raw_email)
        return super().filter(*args, **kwargs)


class MessagingRecord(UUIDTModel):
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
