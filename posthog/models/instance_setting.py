import json
from contextlib import contextmanager
from typing import Any, List

import structlog
from django.core.cache import cache
from django.db import Error as DjangoDatabaseError
from django.db import models

from posthog.settings import CONSTANCE_CONFIG, CONSTANCE_DATABASE_PREFIX

logger = structlog.get_logger(__name__)


class InstanceSetting(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["key"], name="unique key")]

    key: models.CharField = models.CharField(max_length=128, null=False, blank=False)
    raw_value: models.CharField = models.CharField(max_length=1024, null=False, blank=True)

    @property
    def value(self):
        return json.loads(self.raw_value)

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete(self.key.replace(CONSTANCE_DATABASE_PREFIX, ""))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.set(self.key.replace(CONSTANCE_DATABASE_PREFIX, ""), self.raw_value)


def get_instance_setting(key: str) -> Any:
    assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    cached_setting = cache.get(key)
    if cached_setting:
        return json.loads(cached_setting)

    try:
        saved_setting = InstanceSetting.objects.filter(key=CONSTANCE_DATABASE_PREFIX + key).first()
    except DjangoDatabaseError as e:
        logger.exception("Unable to get instance setting %s due to database error", key, exc=e)
        saved_setting = None

    if saved_setting is not None:
        cache.set(key, saved_setting.raw_value)
        return saved_setting.value
    else:
        return CONSTANCE_CONFIG[key][0]  # Get the default value


def get_instance_settings(keys: List[str]) -> Any:
    for key in keys:
        assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    saved_settings = InstanceSetting.objects.filter(key__in=[CONSTANCE_DATABASE_PREFIX + key for key in keys]).all()
    response = {key: CONSTANCE_CONFIG[key][0] for key in keys}

    for setting in saved_settings:
        key = setting.key.replace(CONSTANCE_DATABASE_PREFIX, "")
        response[key] = setting.value

    return response


def set_instance_setting(key: str, value: Any):
    raw_value = json.dumps(value)
    InstanceSetting.objects.update_or_create(key=CONSTANCE_DATABASE_PREFIX + key, defaults={"raw_value": raw_value})


@contextmanager
def override_instance_config(key: str, value: Any):
    current_value = get_instance_setting(key)
    set_instance_setting(key, value)

    try:
        yield
    finally:
        set_instance_setting(key, current_value)
