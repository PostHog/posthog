import json
from typing import cast
from unittest.mock import patch

import pytest

import posthog.settings as settings
from posthog.models.instance_setting import (
    InstanceSetting,
    get_instance_setting,
    get_instance_settings,
    override_instance_config,
    set_instance_setting,
)


def test_unknown_key_raises(db):
    with pytest.raises(AssertionError):
        get_instance_setting("UNKNOWN_SETTING")


def test_initial_value_and_overriding(db):
    assert get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")

    set_instance_setting("MATERIALIZED_COLUMNS_ENABLED", False)
    assert not get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")

    set_instance_setting("MATERIALIZED_COLUMNS_ENABLED", True)
    assert get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")


def test_model_creation(db):
    set_instance_setting("MATERIALIZED_COLUMNS_ENABLED", "foobar")

    instance = cast(InstanceSetting, InstanceSetting.objects.first())
    assert instance.key == "constance:posthog:MATERIALIZED_COLUMNS_ENABLED"
    assert instance.value == "foobar"
    assert instance.raw_value == '"foobar"'

    set_instance_setting("MATERIALIZED_COLUMNS_ENABLED", True)

    instance = cast(InstanceSetting, InstanceSetting.objects.first())
    assert instance.key == "constance:posthog:MATERIALIZED_COLUMNS_ENABLED"
    assert instance.value is True
    assert instance.raw_value == "true"


def test_override_constance_config(db):
    set_instance_setting("MATERIALIZED_COLUMNS_ENABLED", True)

    assert get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")
    with override_instance_config("MATERIALIZED_COLUMNS_ENABLED", False):
        assert not get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")
    assert get_instance_setting("MATERIALIZED_COLUMNS_ENABLED")


def test_can_retrieve_multiple_settings(db):
    set_instance_setting("MATERIALIZED_COLUMNS_ENABLED", True)
    set_instance_setting("ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT", 20000)

    assert get_instance_setting("MATERIALIZED_COLUMNS_ENABLED") is True
    assert get_instance_setting("ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT") == 20000

    returned = get_instance_settings(
        ["MATERIALIZED_COLUMNS_ENABLED", "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT", "ASYNC_MIGRATIONS_AUTO_CONTINUE"]
    )

    assert returned == {
        "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT": 20000,
        "MATERIALIZED_COLUMNS_ENABLED": True,
        "ASYNC_MIGRATIONS_AUTO_CONTINUE": True,
    }


@pytest.mark.parametrize(
    "cached_value", ("true", '["1:cool","abc:123","123:b83b5ca6-:6fa2:d28a:2759"]', '"a_string"', "123")
)
def test_get_cached_instance_setting(db, cache, cached_value):
    """Test a deserialized cached value will be returned when available instead of querying db."""
    key = "my_key"
    patched = {key: ("default_value", "a help str", str)}

    with patch.dict(settings.CONSTANCE_CONFIG, patched, clear=True):
        default_value = get_instance_setting(key)
        # Ensure value is not initially set, so default is returned
        assert default_value == "default_value"

        cache.set(key, cached_value)
        value = get_instance_setting(key)

        assert value == json.loads(cached_value)


@pytest.mark.parametrize(
    "raw_value", ("true", '["1:cool","abc:123","123:b83b5ca6-:6fa2:d28a:2759"]', '"a_string"', "123")
)
def test_get_instance_setting_sets_cache(db, cache, raw_value):
    """Test cache is set after calling get_instance_settings the first time."""
    key = "my_key"
    patched = {key: ("default_value", "a help str", str)}

    InstanceSetting.objects.create(key=settings.CONSTANCE_DATABASE_PREFIX + key, raw_value=raw_value)

    with patch.dict(settings.CONSTANCE_CONFIG, patched, clear=True):
        assert cache.get(key) is None

        first_value = get_instance_setting(key)
        assert first_value == json.loads(raw_value)
        assert cache.get(key) == raw_value

        second_value = get_instance_setting(key)
        assert second_value == json.loads(raw_value)
