from typing import cast

import pytest

from posthog.models.constance import Constance, get_dynamic_setting, override_constance_config, set_dynamic_setting


def test_unknown_key_raises(db):
    with pytest.raises(AssertionError):
        get_dynamic_setting("UNKNOWN_SETTING")


def test_initial_value_and_overriding(db):
    assert get_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED")

    set_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED", False)
    assert not get_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED")

    set_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED", True)
    assert get_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED")


def test_model_creation(db):
    set_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED", "foobar")

    instance = cast(Constance, Constance.objects.first())
    assert instance.key == "constance:posthog:MATERIALIZED_COLUMNS_ENABLED"
    assert instance.value == "foobar"
    assert instance.raw_value == '"foobar"'

    set_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED", True)

    instance = cast(Constance, Constance.objects.first())
    assert instance.key == "constance:posthog:MATERIALIZED_COLUMNS_ENABLED"
    assert instance.value is True
    assert instance.raw_value == "true"


def test_override_constance_config(db):
    set_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED", True)

    assert get_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED")
    with override_constance_config("MATERIALIZED_COLUMNS_ENABLED", False):
        assert not get_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED")
    assert get_dynamic_setting("MATERIALIZED_COLUMNS_ENABLED")
