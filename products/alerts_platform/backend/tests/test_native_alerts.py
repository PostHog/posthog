from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from pydantic import BaseModel, ConfigDict

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import (
    Grouping,
    IncidentAction,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic import platform_writes
from products.alerts_platform.backend.models import PlatformAlertConfiguration

_SOURCE_CONFIGS = "products.alerts_platform.backend.logic.source_configs.spec"
_DELIVER_INLINE = "products.alerts_platform.backend.temporal.web_start.deliver_inline"


class _WatchedRows(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_ids: list[str] = []


def _edit(**changes: object) -> PlatformAlertConfigurationEdit:
    edit = PlatformAlertConfigurationEdit(
        name="Sync failures",
        enabled=True,
        source_config={"row_ids": ["a"]},
        grouping=Grouping(),
        schedule_restriction=None,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
    )
    return replace(edit, **changes)  # type: ignore[arg-type]


class TestNativeAlerts(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.check_in_team = MagicMock()
        self.remove_destinations = MagicMock()
        self.spec = SourceConfigSpec(
            model=_WatchedRows,
            validate=lambda edit: None,
            check_in_team=self.check_in_team,
            incident_event_ids={
                IncidentAction.TRIGGER: "$x_alert_incident_opened",
                IncidentAction.RESOLVE: "$x_alert_incident_closed",
            },
            alert_url=lambda team_id, alert_id: f"https://example.com/{team_id}/{alert_id}",
            native=NativeAlertLifecycle(
                check_interval_minutes=5,
                remove_destinations=self.remove_destinations,
            ),
        )
        patcher = patch(_SOURCE_CONFIGS, return_value=self.spec)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create(self) -> UUID:
        with team_scope(self.team.id):
            view = platform_writes.create_configuration(
                team_id=self.team.id, source_kind=SourceKind.LOGS, edit=_edit(), created_by_id=self.user.id
            )
        return view.id

    def test_a_native_create_writes_one_platform_owned_configuration_and_no_source_row(self) -> None:
        configuration_id = self._create()

        with team_scope(self.team.id):
            configuration = PlatformAlertConfiguration.objects.get(id=configuration_id)
        assert (
            configuration.owner,
            configuration.legacy_configuration_id,
            configuration.check_interval_minutes,
            configuration.source_config,
        ) == (PlatformAlertOwner.PLATFORM, None, 5, {"row_ids": ["a"]})
        self.check_in_team.assert_called_once_with(team_id=self.team.id, edit=_edit())
        assert (
            ActivityLog.objects.filter(
                scope="PlatformAlertConfiguration", item_id=str(configuration_id), activity="created"
            ).count()
            == 1
        )

    @parameterized.expand(
        [
            ("rename", {"name": "Renamed"}, False),
            ("source_config", {"source_config": {"row_ids": ["b"]}}, True),
        ]
    )
    def test_a_native_edit_checks_the_project_only_when_source_config_changes(
        self, _name: str, changes: dict[str, object], checked: bool
    ) -> None:
        configuration_id = self._create()
        self.check_in_team.reset_mock()
        self.check_in_team.side_effect = InvalidPlatformAlertEdit("source_config", "Not in this project.")

        with pytest.raises(InvalidPlatformAlertEdit) if checked else nullcontext(), team_scope(self.team.id):
            platform_writes.update_configuration(
                team_id=self.team.id,
                source_kinds=[SourceKind.LOGS.value],
                configuration_id=configuration_id,
                change=lambda current: replace(current, **changes),  # type: ignore[arg-type]
            )

        assert self.check_in_team.called is checked

    def test_deleting_a_firing_native_alert_resolves_by_its_own_id_before_its_destinations_go(self) -> None:
        configuration_id = self._create()
        with team_scope(self.team.id):
            platform_testing.start_firing(configuration_id, team_id=self.team.id, at=datetime(2026, 1, 1, tzinfo=UTC))
        calls: list[str] = []

        with patch(_DELIVER_INLINE, side_effect=lambda request: calls.append(request.destination_alert_id)):
            self.remove_destinations.side_effect = lambda **_: calls.append("destinations removed")
            with team_scope(self.team.id):
                deleted = platform_writes.delete_configuration(
                    team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], configuration_id=configuration_id
                )

        assert deleted
        assert calls == [str(configuration_id), "destinations removed"]
        self.remove_destinations.assert_called_once_with(team_id=self.team.id, configuration_id=configuration_id)
        with team_scope(self.team.id):
            assert not PlatformAlertConfiguration.objects.filter(id=configuration_id).exists()

    def test_a_native_delete_that_fails_keeps_what_removing_the_destinations_wrote(self) -> None:
        configuration_id = self._create()

        def remove_destinations(**_: object) -> None:
            with team_scope(self.team.id):
                PlatformAlertConfiguration.objects.filter(id=configuration_id).update(name="Destinations removed")

        self.remove_destinations.side_effect = remove_destinations
        with (
            patch.object(PlatformAlertConfiguration, "delete", side_effect=RuntimeError("delete failed")),
            pytest.raises(RuntimeError),
            team_scope(self.team.id),
        ):
            platform_writes.delete_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], configuration_id=configuration_id
            )

        with team_scope(self.team.id):
            assert PlatformAlertConfiguration.objects.get(id=configuration_id).name == "Sync failures"
