from dataclasses import replace
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import (
    ControlChangeKind,
    Grouping,
    PlatformAlertConfigurationEdit,
)
from products.alerts_platform.backend.facade.enums import OnMissingData
from products.alerts_platform.backend.logic.control_plane import change_kind, ending_reason

CURRENT = PlatformAlertConfigurationEdit(
    name="Error rate",
    enabled=True,
    source_config={"threshold": 5},
    grouping=Grouping(),
    schedule_restriction=None,
    evaluation_periods=1,
    datapoints_to_alarm=1,
    cooldown_minutes=0,
)


class TestControlPlaneSettings(SimpleTestCase):
    @parameterized.expand(
        [
            ("threshold", {"source_config": {"threshold": 10}}, "config_changed", ControlChangeKind.CONFIG_CHANGE),
            ("missing_data", {"on_missing_data": OnMissingData.KEEP_LAST_STATE}, None, ControlChangeKind.CONFIG_CHANGE),
            ("rename", {"name": "Errors"}, None, None),
        ]
    )
    def test_an_edit_ends_firings_and_records_a_change(
        self,
        _name: str,
        changes: dict[str, Any],
        expected_ending: str | None,
        expected_kind: ControlChangeKind | None,
    ) -> None:
        edit = replace(CURRENT, **changes)

        assert ending_reason(CURRENT, edit, regrouped=False, snoozing=False) == expected_ending
        assert change_kind(CURRENT, edit, regrouped=False, snooze_changed=False, snooze_until=None) == expected_kind
