import json
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from django.db import models

from posthog.settings import CONSTANCE_CONFIG, CONSTANCE_DATABASE_PREFIX


class InstanceSetting(models.Model):
    key = models.CharField(max_length=128, null=False, blank=False)
    raw_value = models.CharField(max_length=1024, null=False, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key"], name="unique key")]

    @property
    def value(self):
        return json.loads(self.raw_value)


@lru_cache
def get_instance_setting(key: str) -> Any:
    assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    saved_setting = InstanceSetting.objects.filter(key=CONSTANCE_DATABASE_PREFIX + key).first()
    if saved_setting is not None:
        return saved_setting.value
    else:
        return CONSTANCE_CONFIG[key][0]  # Get the default value


def get_instance_settings(keys: list[str]) -> Any:
    for key in keys:
        assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    saved_settings = InstanceSetting.objects.filter(key__in=[CONSTANCE_DATABASE_PREFIX + key for key in keys]).all()
    response = {key: CONSTANCE_CONFIG[key][0] for key in keys}

    for setting in saved_settings:
        key = setting.key.replace(CONSTANCE_DATABASE_PREFIX, "")
        response[key] = setting.value

    return response


def set_instance_setting(key: str, value: Any):
    InstanceSetting.objects.update_or_create(
        key=CONSTANCE_DATABASE_PREFIX + key, defaults={"raw_value": json.dumps(value)}
    )
    get_instance_setting.cache_clear()


@contextmanager
def override_instance_config(key: str, value: Any):
    current_value = get_instance_setting(key)
    set_instance_setting(key, value)

    try:
        yield
    finally:
        set_instance_setting(key, current_value)
