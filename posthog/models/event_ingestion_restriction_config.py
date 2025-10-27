import json

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.utils import UUIDTModel
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL

DYNAMIC_CONFIG_REDIS_KEY_PREFIX = "event_ingestion_restriction_dynamic_config"


class RestrictionType(models.TextChoices):
    SKIP_PERSON_PROCESSING = "skip_person_processing"
    DROP_EVENT_FROM_INGESTION = "drop_event_from_ingestion"
    FORCE_OVERFLOW_FROM_INGESTION = "force_overflow_from_ingestion"


class EventIngestionRestrictionConfig(UUIDTModel):
    """
    Configuration for various restrictions we can set by token or token:distinct_id
    """

    token = models.CharField(max_length=100)
    restriction_type = models.CharField(max_length=100, choices=RestrictionType.choices)
    distinct_ids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    note = models.TextField(
        blank=True, null=True, help_text="Optional note explaining why this restriction was put in place"
    )
    analytics = models.BooleanField(
        default=True, help_text="Whether this restriction applies to the analytics ingestion pipeline"
    )
    session_recordings = models.BooleanField(
        default=False, help_text="Whether this restriction applies to the session recordings ingestion pipeline"
    )

    class Meta:
        unique_together = ("token", "restriction_type")

    def get_redis_key(self):
        return f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{self.restriction_type}"


@receiver(post_save, sender=EventIngestionRestrictionConfig)
def update_redis_cache_with_config(sender, instance, created=False, **kwargs):
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)
    redis_key = instance.get_redis_key()

    existing_config = redis_client.get(redis_key)
    data = json.loads(existing_config) if existing_config else []

    # Remove existing entries for this token (both simple and distinct_id based)
    data = [
        entry
        for entry in data
        if not (
            (isinstance(entry, str) and (entry == instance.token or entry.startswith(f"{instance.token}:")))
            or (isinstance(entry, dict) and entry.get("token") == instance.token)
        )
    ]

    # Add new entries with pipeline information
    entry_base = {
        "token": instance.token,
        "analytics": instance.analytics,
        "session_recordings": instance.session_recordings,
    }

    if instance.distinct_ids:
        for distinct_id in instance.distinct_ids:
            entry = entry_base.copy()
            entry["distinct_id"] = distinct_id
            data.append(entry)
    else:
        data.append(entry_base)

    redis_client.set(redis_key, json.dumps(data))


@receiver(post_delete, sender=EventIngestionRestrictionConfig)
def delete_redis_cache_with_config(sender, instance, **kwargs):
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)
    redis_key = instance.get_redis_key()

    existing_data = redis_client.get(redis_key)
    if existing_data:
        data = json.loads(existing_data)

        # Remove entries for this token (handle both old string format and new dict format)
        data = [
            entry
            for entry in data
            if not (
                (isinstance(entry, str) and (entry == instance.token or entry.startswith(f"{instance.token}:")))
                or (isinstance(entry, dict) and entry.get("token") == instance.token)
            )
        ]

        if data:
            redis_client.set(redis_key, json.dumps(data))
        else:
            redis_client.delete(redis_key)
