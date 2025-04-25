from posthog.models.utils import UUIDModel
from posthog.redis import get_client
from posthog.settings import PLUGINS_RELOAD_REDIS_URL
from django.db.models.signals import post_save
from django.db import models
from django.dispatch import receiver
from django.contrib.postgres.fields import ArrayField
import json


class TokenRestrictionConfig(UUIDModel):
    """
    Configuration for various restrictions we can set by token or token:distinct_id
    """

    team = models.OneToOneField("Team", on_delete=models.CASCADE)
    tokens_to_skip_person_processing = ArrayField(models.CharField(max_length=450), default=list, blank=True, null=True)
    tokens_to_drop_events_from_ingestion = ArrayField(
        models.CharField(max_length=450), default=list, blank=True, null=True
    )
    tokens_to_force_overflow_from_ingestion = ArrayField(
        models.CharField(max_length=450), default=list, blank=True, null=True
    )
    # Redis key prefixes for caching
    SKIP_PERSON_KEY_FORMAT = "skip_person:{}"
    DROP_EVENT_FROM_INGESTION_KEY_FORMAT = "drop_event_from_ingestion:{}"
    FORCE_OVERFLOW_FROM_INGESTION_KEY_FORMAT = "force_overflow_from_ingestion:{}"

    def get_skip_person_key(self):
        return self.SKIP_PERSON_KEY_FORMAT.format(self.team.api_token)

    def get_drop_event_key_from_ingestion(self):
        return self.DROP_EVENT_FROM_INGESTION_KEY_FORMAT.format(self.team.api_token)

    def get_force_overflow_key_from_ingestion(self):
        return self.FORCE_OVERFLOW_FROM_INGESTION_KEY_FORMAT.format(self.team.api_token)


@receiver(post_save, sender=TokenRestrictionConfig)
def update_redis_cache_with_config(sender, instance, **kwargs):
    redis_client = get_client(PLUGINS_RELOAD_REDIS_URL)

    skip_person_key = instance.get_skip_person_key()
    if instance.tokens_to_skip_person_processing:
        redis_client.set(skip_person_key, json.dumps(instance.tokens_to_skip_person_processing))
    else:
        redis_client.delete(skip_person_key)

    drop_event_key = instance.get_drop_event_key_from_ingestion()
    if instance.tokens_to_drop_events_from_ingestion:
        redis_client.set(drop_event_key, json.dumps(instance.tokens_to_drop_events_from_ingestion))
    else:
        redis_client.delete(drop_event_key)

    force_overflow_key = instance.get_force_overflow_key_from_ingestion()
    if instance.tokens_to_force_overflow_from_ingestion:
        redis_client.set(force_overflow_key, json.dumps(instance.tokens_to_force_overflow_from_ingestion))
    else:
        redis_client.delete(force_overflow_key)
