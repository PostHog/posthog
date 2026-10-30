import json

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from posthog.models.utils import UUIDTModel
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL

DYNAMIC_CONFIG_REDIS_KEY_PREFIX = "event_ingestion_restriction_dynamic_config"

# A typo guard for staff input. Capture clamps an override lower still, to what its Kafka producer accepts.
MAX_AI_EVENT_BYTES_OVERRIDE = 64 * 1024 * 1024

RESTRICTION_FILTER_FIELDS = ("distinct_ids", "session_ids", "event_names", "event_uuids")

# Pipeline configuration - first item is the default
INGESTION_PIPELINES = [
    {"value": "analytics", "label": "Analytics Pipeline"},
    {"value": "session_recordings", "label": "Session Recordings Pipeline"},
    {"value": "errortracking", "label": "Error Tracking Pipeline"},
    {"value": "clientwarnings", "label": "Client Warnings Pipeline"},
    {"value": "heatmaps", "label": "Heatmaps Pipeline"},
    {"value": "ai", "label": "AI Pipeline"},
]


def default_pipelines():
    return ["analytics"]


class RestrictionType(models.TextChoices):
    SKIP_PERSON_PROCESSING = "skip_person_processing"
    DROP_EVENT_FROM_INGESTION = "drop_event_from_ingestion"
    FORCE_OVERFLOW_FROM_INGESTION = "force_overflow_from_ingestion"
    REDIRECT_TO_DLQ = "redirect_to_dlq"
    REDIRECT_TO_TOPIC = "redirect_to_topic"
    # A grant, not a restriction: raises the token's AI event size cap in capture. Shares this model
    # for its admin page, Redis sync and refresh loop, so it stays out of the project-facing API.
    OVERRIDE_AI_MAX_EVENT_BYTES = "override_ai_max_event_bytes", "Override AI max event bytes"


class IngestionPipeline(models.TextChoices):
    ANALYTICS = "analytics"
    SESSION_RECORDINGS = "session_recordings"
    ERRORTRACKING = "errortracking"
    CLIENTWARNINGS = "clientwarnings"
    HEATMAPS = "heatmaps"
    AI = "ai"


class EventIngestionRestrictionConfig(UUIDTModel):
    """
    Configuration for various restrictions we can set by token, token:distinct_id, token:session_id,
    token:event_name, or token:event_uuid
    """

    token = models.CharField(max_length=100)
    restriction_type = models.CharField(max_length=100, choices=RestrictionType)
    distinct_ids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    session_ids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    event_names = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    event_uuids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    args = models.JSONField(
        blank=True,
        null=True,
        help_text='Extra arguments for the restriction type (e.g., {"topic": "my_topic"} for redirect_to_topic)',
    )
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

        # Validate args for redirect_to_topic
        if self.restriction_type == RestrictionType.REDIRECT_TO_TOPIC:
            if not isinstance(self.args, dict):
                raise ValidationError({"args": "args must be a JSON object for redirect_to_topic"})
            topic = self.args.get("topic")
            if not isinstance(topic, str) or not topic.strip():
                raise ValidationError({"args": 'args must contain a non-empty "topic" string for redirect_to_topic'})

        if self.restriction_type == RestrictionType.OVERRIDE_AI_MAX_EVENT_BYTES:
            self._clean_ai_max_event_bytes_override()

    def _clean_ai_max_event_bytes_override(self):
        errors: dict[str, str] = {}
        if self.pipelines != [IngestionPipeline.AI.value]:
            errors["pipelines"] = "An AI event size override applies to the AI pipeline only. Select just 'ai'."
        for field in RESTRICTION_FILTER_FIELDS:
            if getattr(self, field):
                errors[field] = "An AI event size override applies to every event of the token. Leave this empty."
        max_event_bytes = self.args.get("max_event_bytes") if isinstance(self.args, dict) else None
        # Keyed on NON_FIELD_ERRORS because the admin form has no `args` field, and a model error on a
        # field the form lacks is a ValueError there, not a message.
        if type(max_event_bytes) is not int or not 1 <= max_event_bytes <= MAX_AI_EVENT_BYTES_OVERRIDE:
            errors[NON_FIELD_ERRORS] = (
                f"Max event bytes must be an integer between 1 and {MAX_AI_EVENT_BYTES_OVERRIDE} "
                f'(args: {{"max_event_bytes": <int>}}).'
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def get_redis_key(self):
        return f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{self.restriction_type}"

    def add_distinct_id(self, distinct_id: str) -> bool:
        """Add a distinct_id to this restriction. Returns True if added, False if already present."""
        current = self.distinct_ids or []
        if distinct_id in current:
            return False
        self.distinct_ids = [*current, distinct_id]
        self.save()
        return True

    @classmethod
    def add_distinct_id_for_token(
        cls, token: str, restriction_type: str, distinct_id: str
    ) -> tuple["EventIngestionRestrictionConfig", bool, bool]:
        """Get or create a restriction and add a distinct_id.

        Returns (restriction, was_created, was_added).
        """
        try:
            restriction = cls.objects.get(token=token, restriction_type=restriction_type)
            added = restriction.add_distinct_id(distinct_id)
            return restriction, False, added
        except cls.DoesNotExist:
            restriction = cls.objects.create(
                token=token,
                restriction_type=restriction_type,
                distinct_ids=[distinct_id],
            )
            return restriction, True, True


def regenerate_redis_for_restriction_type(restriction_type: str):
    """
    Regenerate the Redis cache for a specific restriction type by fetching all configs from the database.

    Generates v2 format with arrays for each filter type. Filter logic (matching Rust implementation):
    - AND between filter types (distinct_ids AND session_ids AND event_names AND event_uuids)
    - OR within each filter type (value in array)
    - Empty array = matches all (neutral in AND)
    """
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)
    redis_key = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{restriction_type}"

    # Fetch all restrictions of this type, ordered by id (UUIDT, time-sortable) ascending.
    # The index field in the output reflects this order so consumers can determine
    # which config was created most recently (highest index wins for redirect_to_topic).
    configs = list(EventIngestionRestrictionConfig.objects.filter(restriction_type=restriction_type).order_by("id"))

    if not configs:
        # No configs exist, delete the Redis key
        redis_client.delete(redis_key)
        return

    # Build the new data array from all configs in the database (v2 format)
    data = []
    for index, config in enumerate(configs):
        entry = {
            "version": 2,
            "index": index,
            "token": config.token,
            "pipelines": config.pipelines or [],
            "distinct_ids": config.distinct_ids or [],
            "session_ids": config.session_ids or [],
            "event_names": config.event_names or [],
            "event_uuids": config.event_uuids or [],
            "args": config.args,
        }
        data.append(entry)

    redis_client.set(redis_key, json.dumps(data))


@receiver(pre_save, sender=EventIngestionRestrictionConfig)
def capture_old_restriction_type(sender, instance, **kwargs):
    """Capture the old restriction_type before save to handle type changes."""
    if instance.pk:
        try:
            old_instance = EventIngestionRestrictionConfig.objects.get(pk=instance.pk)
            instance._old_restriction_type = old_instance.restriction_type
        except EventIngestionRestrictionConfig.DoesNotExist:
            instance._old_restriction_type = None
    else:
        instance._old_restriction_type = None


@receiver(post_save, sender=EventIngestionRestrictionConfig)
def update_redis_cache_with_config(sender, instance, created=False, **kwargs):
    regenerate_redis_for_restriction_type(instance.restriction_type)

    # If restriction_type changed, also regenerate the old type's Redis key
    old_restriction_type = getattr(instance, "_old_restriction_type", None)
    if old_restriction_type and old_restriction_type != instance.restriction_type:
        regenerate_redis_for_restriction_type(old_restriction_type)


@receiver(post_delete, sender=EventIngestionRestrictionConfig)
def delete_redis_cache_with_config(sender, instance, **kwargs):
    regenerate_redis_for_restriction_type(instance.restriction_type)
