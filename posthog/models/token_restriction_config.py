from posthog.models.utils import UUIDModel
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL
from django.db.models.signals import post_save, post_delete
from django.db import models
from django.dispatch import receiver
from django.contrib.postgres.fields import ArrayField
import json


class RestrictionType(models.TextChoices):
    # fix these
    SKIP_PERSON_PROCESSING = "skip_person_processing"
    DROP_EVENTS_FROM_INGESTION = "drop_events_from_ingestion"
    FORCE_OVERFLOW_FROM_INGESTION = "force_overflow_from_ingestion"


class TokenRestrictionConfig(UUIDModel):
    """
    Configuration for various restrictions we can set by token or token:distinct_id
    """

    # figure out blank or null or what?
    token = models.CharField(max_length=100)
    restriction_type = models.CharField(max_length=100, choices=RestrictionType.choices)
    distinct_ids = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    enabled = models.BooleanField(default=True)

    # Redis key prefixes for caching
    SKIP_PERSON_KEY_FORMAT = "skip_person:{}"
    DROP_EVENT_FROM_INGESTION_KEY_FORMAT = "drop_event_from_ingestion:{}"
    FORCE_OVERFLOW_FROM_INGESTION_KEY_FORMAT = "force_overflow_from_ingestion:{}"

    class Meta:
        unique_together = ("token", "restriction_type")

    def get_redis_key(self):
        if self.restriction_type == RestrictionType.SKIP_PERSON_PROCESSING:
            return self.SKIP_PERSON_KEY_FORMAT.format(self.token)
        elif self.restriction_type == RestrictionType.DROP_EVENTS:
            return self.DROP_EVENT_FROM_INGESTION_KEY_FORMAT.format(self.token)
        elif self.restriction_type == RestrictionType.FORCE_OVERFLOW:
            return self.FORCE_OVERFLOW_FROM_INGESTION_KEY_FORMAT.format(self.token)
        return None


@receiver(post_save, sender=TokenRestrictionConfig)
def update_redis_cache_with_config(sender, instance, **kwargs):
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)

    redis_key = instance.get_redis_key()
    if redis_key:
        if not instance.enabled:
            redis_client.delete(redis_key)
            return
        if instance.distinct_ids:
            redis_client.set(redis_key, json.dumps(instance.distinct_ids))
        else:
            redis_client.set(redis_key, json.dumps([instance.token]))


@receiver(post_delete, sender=TokenRestrictionConfig)
def delete_redis_cache_with_config(sender, instance, **kwargs):
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)
    redis_key = instance.get_redis_key()
    if redis_key:
        redis_client.delete(redis_key)
