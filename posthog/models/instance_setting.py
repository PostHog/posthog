import json
from contextlib import contextmanager
from typing import Any

from django.db import models

from posthog.settings import CONSTANCE_CONFIG, CONSTANCE_DATABASE_PREFIX


class InstanceSetting(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["key"], name="unique key",)]

    key: models.CharField = models.CharField(max_length=128, null=False, blank=False)
    raw_value: models.CharField = models.CharField(max_length=1024, null=False, blank=True)

    @property
    def value(self):
        return json.loads(self.raw_value)


def get_instance_setting(key: str) -> Any:
    assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    saved_setting = InstanceSetting.objects.filter(key=CONSTANCE_DATABASE_PREFIX + key).first()
    if saved_setting is not None:
        return saved_setting.value
    else:
        return CONSTANCE_CONFIG[key][0]  # Get the default value


def set_instance_setting(key: str, value: Any):
    InstanceSetting.objects.update_or_create(
        key=CONSTANCE_DATABASE_PREFIX + key, defaults={"raw_value": json.dumps(value)},
    )


@contextmanager
def override_instance_config(key: str, value: Any):
    current_value = get_instance_setting(key)
    set_instance_setting(key, value)

    try:
        yield
    finally:
        set_instance_setting(key, current_value)
