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
    REDIRECT_TO_DLQ = "redirect_to_dlq"


class IngestionPipeline(models.TextChoices):
    ANALYTICS = "analytics"
    SESSION_RECORDINGS = "session_recordings"


class EventIngestionRestrictionConfig(UUIDTModel):
    """
    Configuration for various restrictions we can set by token, token:distinct_id, token:session_id,
    token:event_name, or token:event_uuid
    """

    token = models.CharField(max_length=100)
    restriction_type = models.CharField(max_length=100, choices=RestrictionType.choices)
    distinct_ids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    session_ids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    event_names = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    event_uuids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
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


def regenerate_redis_for_restriction_type(restriction_type: str):
    """Regenerate the Redis cache for a specific restriction type by fetching all configs from the database"""
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)
    redis_key = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{restriction_type}"

    # Fetch all restrictions of this type from the database
    configs = list(EventIngestionRestrictionConfig.objects.filter(restriction_type=restriction_type))

    if not configs:
        # No configs exist, delete the Redis key
        redis_client.delete(redis_key)
        return

    # Build the new data array from all configs in the database
    data = []
    for config in configs:
        entry_base = {
            "token": config.token,
            "pipelines": config.pipelines or [],
        }

        has_specific_filters = config.distinct_ids or config.session_ids or config.event_names or config.event_uuids

        if not has_specific_filters:
            # No specific IDs - applies to all events for this token
            data.append(entry_base)
        else:
            # Add entries for each distinct_id
            if config.distinct_ids:
                for distinct_id in config.distinct_ids:
                    entry = entry_base.copy()
                    entry["distinct_id"] = distinct_id
                    data.append(entry)

            # Add entries for each session_id
            if config.session_ids:
                for session_id in config.session_ids:
                    entry = entry_base.copy()
                    entry["session_id"] = session_id
                    data.append(entry)

            # Add entries for each event_name
            if config.event_names:
                for event_name in config.event_names:
                    entry = entry_base.copy()
                    entry["event_name"] = event_name
                    data.append(entry)

            # Add entries for each event_uuid
            if config.event_uuids:
                for event_uuid in config.event_uuids:
                    entry = entry_base.copy()
                    entry["event_uuid"] = event_uuid
                    data.append(entry)

    redis_client.set(redis_key, json.dumps(data))


@receiver(post_save, sender=EventIngestionRestrictionConfig)
def update_redis_cache_with_config(sender, instance, created=False, **kwargs):
    regenerate_redis_for_restriction_type(instance.restriction_type)


@receiver(post_delete, sender=EventIngestionRestrictionConfig)
def delete_redis_cache_with_config(sender, instance, **kwargs):
    regenerate_redis_for_restriction_type(instance.restriction_type)
