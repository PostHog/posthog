from typing import cast

import pytest

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
        [
            "MATERIALIZED_COLUMNS_ENABLED",
            "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT",
            "ASYNC_MIGRATIONS_AUTO_CONTINUE",
        ]
    )

    assert returned == {
        "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT": 20000,
        "MATERIALIZED_COLUMNS_ENABLED": True,
        "ASYNC_MIGRATIONS_AUTO_CONTINUE": True,
    }


def test_value_property_handles_bare_strings(db):
    """raw_value may be a bare string (e.g. saved via Django admin without json.dumps wrapping).
    The value property should return it as-is instead of raising JSONDecodeError."""
    instance = InstanceSetting.objects.create(
        key="constance:posthog:TEST_BARE_HEX", raw_value="1ee937c5cba4da2dbdce84824cfa0e93"
    )
    assert instance.value == "1ee937c5cba4da2dbdce84824cfa0e93"

    # String with dots
    instance2 = InstanceSetting.objects.create(
        key="constance:posthog:TEST_BARE_DOTTED", raw_value="910200304849.9220719972545"
    )
    assert instance2.value == "910200304849.9220719972545"

    # Empty string
    instance3 = InstanceSetting.objects.create(key="constance:posthog:TEST_BARE_EMPTY", raw_value="")
    assert instance3.value == ""

    # Valid JSON values still work as before
    instance4 = InstanceSetting.objects.create(key="constance:posthog:TEST_VALID_JSON_STR", raw_value='"hello"')
    assert instance4.value == "hello"

    instance5 = InstanceSetting.objects.create(key="constance:posthog:TEST_VALID_JSON_BOOL", raw_value="true")
    assert instance5.value is True

    instance6 = InstanceSetting.objects.create(key="constance:posthog:TEST_VALID_JSON_INT", raw_value="42")
    assert instance6.value == 42


def test_admin_save_model_wraps_bare_strings(db):
    """Django admin save_model should auto-wrap bare strings with json.dumps()."""

    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory

    from posthog.admin.admins.instance_setting_admin import InstanceSettingAdmin

    site = AdminSite()
    admin = InstanceSettingAdmin(InstanceSetting, site)
    factory = RequestFactory()
    request = factory.post("/admin/posthog/instancesetting/add/")

    # Bare string should be wrapped
    obj = InstanceSetting(key="constance:posthog:TEST_ADMIN_BARE", raw_value="abc123")
    admin.save_model(request, obj, form=None, change=False)
    assert obj.raw_value == '"abc123"'
    assert obj.value == "abc123"

    # Already-valid JSON string should be preserved
    obj2 = InstanceSetting(key="constance:posthog:TEST_ADMIN_VALID_STR", raw_value='"already_valid"')
    admin.save_model(request, obj2, form=None, change=False)
    assert obj2.raw_value == '"already_valid"'
    assert obj2.value == "already_valid"

    # Valid JSON boolean should be preserved
    obj3 = InstanceSetting(key="constance:posthog:TEST_ADMIN_VALID_BOOL", raw_value="true")
    admin.save_model(request, obj3, form=None, change=False)
    assert obj3.raw_value == "true"
    assert obj3.value is True

    # Valid JSON number should be preserved
    obj4 = InstanceSetting(key="constance:posthog:TEST_ADMIN_VALID_NUM", raw_value="42")
    admin.save_model(request, obj4, form=None, change=False)
    assert obj4.raw_value == "42"
    assert obj4.value == 42
