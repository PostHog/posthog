import json
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from django.db import models
from django.db.utils import OperationalError, ProgrammingError

import structlog

from posthog.settings import CONSTANCE_CONFIG, CONSTANCE_DATABASE_PREFIX

logger = structlog.get_logger(__name__)


class InstanceSetting(models.Model):
    key = models.CharField(max_length=128, null=False, blank=False)
    raw_value = models.CharField(max_length=1024, null=False, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key"], name="unique key")]

    @property
    def value(self):
        try:
            parsed = json.loads(self.raw_value)
        except (json.JSONDecodeError, ValueError):
            # raw_value may be a bare string (e.g. saved via Django admin without json.dumps wrapping)
            return self.raw_value

        # Guard against lossy float parsing: if json.loads parsed a bare numeric string
        # into a float that doesn't round-trip back to the original text, treat it as a
        # bare string rather than silently losing precision.
        if isinstance(parsed, float) and str(parsed) != self.raw_value:
            return self.raw_value

        return parsed


@lru_cache
def _get_instance_setting_cached(key: str) -> Any:
    saved_setting = InstanceSetting.objects.filter(key=CONSTANCE_DATABASE_PREFIX + key).first()
    if saved_setting is not None:
        return saved_setting.value
    return CONSTANCE_CONFIG[key][0]


def get_instance_setting(key: str) -> Any:
    assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    try:
        return _get_instance_setting_cached(key)
    except (ProgrammingError, OperationalError):
        # The posthog_instancesetting table may not exist yet during bootstrap (e.g. running
        # `migrate_clickhouse` before Django migrations have created the Postgres schema, or a
        # cold pod serving the home view before initial migrations land). Fall back to the
        # default without caching, so reads recover automatically once the table is available.
        logger.warning("instance_setting_table_unavailable", key=key)
        return CONSTANCE_CONFIG[key][0]


# Preserve the existing `get_instance_setting.cache_clear()` interface used by `set_instance_setting`
# and test setup.
get_instance_setting.cache_clear = _get_instance_setting_cached.cache_clear  # type: ignore[attr-defined]


def get_instance_settings(keys: list[str]) -> Any:
    for key in keys:
        assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    response = {key: CONSTANCE_CONFIG[key][0] for key in keys}

    try:
        saved_settings = InstanceSetting.objects.filter(key__in=[CONSTANCE_DATABASE_PREFIX + key for key in keys]).all()
        # Force evaluation of the lazy queryset inside the try so a missing table surfaces here.
        saved_settings = list(saved_settings)
    except (ProgrammingError, OperationalError):
        logger.warning("instance_setting_table_unavailable", keys=keys)
        return response

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
