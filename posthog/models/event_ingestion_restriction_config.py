import json

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.utils import UUIDTModel
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL

DYNAMIC_CONFIG_REDIS_KEY_PREFIX = "event_ingestion_restriction_dynamic_config"

# Pipeline configuration - first item is the default
INGESTION_PIPELINES = [
    {"value": "analytics", "label": "Analytics Pipeline"},
    {"value": "session_recordings", "label": "Session Recordings Pipeline"},
]


def default_pipelines():
    return ["analytics"]


class RestrictionType(models.TextChoices):
    SKIP_PERSON_PROCESSING = "skip_person_processing"
    DROP_EVENT_FROM_INGESTION = "drop_event_from_ingestion"
    FORCE_OVERFLOW_FROM_INGESTION = "force_overflow_from_ingestion"


class IngestionPipeline(models.TextChoices):
    ANALYTICS = "analytics"
    SESSION_RECORDINGS = "session_recordings"


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
    pipelines = ArrayField(
        models.CharField(max_length=50),
        default=default_pipelines,
        blank=True,
        help_text="List of ingestion pipelines this restriction applies to (e.g., 'analytics', 'session_recordings')",
    )

    class Meta:
        unique_together = ("token", "restriction_type")

    def clean(self):
        from django.core.exceptions import ValidationError

        # Validate that at least one pipeline is selected
        if not self.pipelines:
            raise ValidationError({"pipelines": "At least one pipeline must be selected"})

        # Validate that all pipeline values are valid
        valid_pipelines = {p["value"] for p in INGESTION_PIPELINES}
        invalid_pipelines = set(self.pipelines) - valid_pipelines
        if invalid_pipelines:
            raise ValidationError(
                {
                    "pipelines": f"Invalid pipeline(s): {', '.join(invalid_pipelines)}. Valid options are: {', '.join(valid_pipelines)}"
                }
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

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
        "pipelines": instance.pipelines or [],
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
