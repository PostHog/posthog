import json
import time
from contextlib import contextmanager
from threading import Lock
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


# Short TTL, not a permanent lru_cache: that pinned each value for a worker's life, so a
# DB-changed setting (e.g. a rotated SMTP password) never reached it without a restart.
_INSTANCE_SETTING_CACHE_TTL_SECONDS = 60
_instance_setting_cache: dict[str, tuple[float, Any]] = {}
_instance_setting_cache_lock = Lock()


def _clear_instance_setting_cache() -> None:
    with _instance_setting_cache_lock:
        _instance_setting_cache.clear()


def get_instance_setting(key: str) -> Any:
    assert key in CONSTANCE_CONFIG, f"Unknown dynamic setting: {repr(key)}"

    with _instance_setting_cache_lock:
        cached = _instance_setting_cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < _INSTANCE_SETTING_CACHE_TTL_SECONDS:
            return cached[1]

    # Fetch outside the lock so a slow query doesn't block other readers.
    saved_setting = InstanceSetting.objects.filter(key=CONSTANCE_DATABASE_PREFIX + key).first()
    value = saved_setting.value if saved_setting is not None else CONSTANCE_CONFIG[key][0]

    with _instance_setting_cache_lock:
        _instance_setting_cache[key] = (time.monotonic(), value)
    return value


# Preserve the lru_cache-era `.cache_clear()` interface that set_instance_setting and tests use.
get_instance_setting.cache_clear = _clear_instance_setting_cache  # type: ignore[attr-defined]


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
    get_instance_setting.cache_clear()  # type: ignore[attr-defined]


@contextmanager
def override_instance_config(key: str, value: Any):
    current_value = get_instance_setting(key)
    set_instance_setting(key, value)

    try:
        yield
    finally:
        set_instance_setting(key, current_value)
