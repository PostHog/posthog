import pytest

from posthog.integrations.backend.patching import changed_fields
from posthog.integrations.contracts import IntegrationPatch
from posthog.models.integration.row_writes import merged_patch, replaced_config_patch, replaced_sensitive_config_patch


@pytest.mark.parametrize(
    "patches,expected_config,expected_errors",
    [
        pytest.param(
            [IntegrationPatch(config_remove=("a",)), IntegrationPatch(config_patch={"a": 2})],
            {"a": 2, "b": 1},
            None,
            id="a_later_set_wins_over_an_earlier_remove",
        ),
        pytest.param(
            [IntegrationPatch(config_patch={"a": 2}), IntegrationPatch(config_remove=("a",))],
            {"b": 1},
            None,
            id="a_later_remove_wins_over_an_earlier_set",
        ),
        pytest.param(
            [IntegrationPatch(errors="failed"), IntegrationPatch(config_patch={"c": 3})],
            {"a": 1, "b": 1, "c": 3},
            "failed",
            id="a_patch_without_errors_keeps_earlier_errors",
        ),
        pytest.param(
            [IntegrationPatch(errors="failed"), IntegrationPatch(errors="")],
            {"a": 1, "b": 1},
            "",
            id="an_empty_errors_clears_earlier_errors",
        ),
    ],
)
def test_merged_patch_applies_the_patches_in_order(
    patches: list[IntegrationPatch], expected_config: dict, expected_errors: str | None
) -> None:
    patch = merged_patch(*patches)
    changed = changed_fields(config={"a": 1, "b": 1}, sensitive_config={}, errors="old", patch=patch)

    assert changed.get("config", {"a": 1, "b": 1}) == expected_config
    assert patch.errors == expected_errors


@pytest.mark.parametrize(
    "current,new,expected",
    [
        pytest.param({"a": 1, "stale": 2}, {"a": 3}, {"a": 3}, id="drops_the_keys_missing_from_the_new_config"),
        pytest.param(
            {"auth_type": "token", "warehouse_source_type": "Stripe", "a": 1},
            {"b": 2},
            {"auth_type": "token", "warehouse_source_type": "Stripe", "b": 2},
            id="keeps_the_keys_that_the_sdk_writes",
        ),
    ],
)
def test_replaced_config_patch(current: dict, new: dict, expected: dict) -> None:
    changed = changed_fields(config=current, sensitive_config={}, errors="", patch=replaced_config_patch(current, new))

    assert changed["config"] == expected


def test_replaced_sensitive_config_patch_drops_every_old_secret() -> None:
    current = {"private_key": "k", "access_token": "old"}
    patch = replaced_sensitive_config_patch(current, {"key_info": dict(current), "access_token": "new"})

    changed = changed_fields(config={}, sensitive_config=current, errors="", patch=patch)

    assert changed["sensitive_config"] == {"key_info": current, "access_token": "new"}
