from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone as django_timezone

from parameterized import parameterized
from pydantic import BaseModel, ConfigDict

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import count_configurations
from products.alerts_platform.backend.facade.contracts import (
    Grouping,
    IncidentAction,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    PlatformAlertCreateRefused,
    PlatformAlertNotEditable,
    SourceConfigSpec,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
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

    def _create(self, *, enabled: bool = True) -> UUID:
        with team_scope(self.team.id):
            view = platform_writes.create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.LOGS,
                edit=_edit(enabled=enabled),
                created_by_id=self.user.id,
            )
        return view.id

    def test_a_native_kind_whose_creates_are_switched_off_refuses_a_create(self) -> None:
        with patch(_SOURCE_CONFIGS, return_value=replace(self.spec, native_create=lambda team_id: False)):
            with pytest.raises(PlatformAlertNotEditable):
                self._create()

        assert count_configurations(team_id=self.team.id, source_kind=SourceKind.LOGS) == 0

    @parameterized.expand([("enabled", True), ("draft_turned_on_later", False)])
    def test_a_native_create_writes_one_platform_owned_configuration_and_no_source_row(
        self, _name: str, enabled: bool
    ) -> None:
        configuration_id = self._create(enabled=enabled)
        if not enabled:
            with team_scope(self.team.id):
                assert PlatformAlertConfiguration.objects.get(id=configuration_id).first_enabled_at is None
                platform_writes.update_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.LOGS.value],
                    configuration_id=configuration_id,
                    change=lambda current: replace(current, enabled=True),
                )

        with team_scope(self.team.id):
            configuration = PlatformAlertConfiguration.objects.get(id=configuration_id)
        assert (
            configuration.owner,
            configuration.legacy_configuration_id,
            configuration.check_interval_minutes,
            configuration.source_config,
            configuration.created_by_id,
            configuration.first_enabled_at is not None,
        ) == (PlatformAlertOwner.PLATFORM, None, 5, {"row_ids": ["a"]}, self.user.id, True)
        self.check_in_team.assert_called_once_with(team_id=self.team.id, edit=_edit(enabled=enabled))
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

    def test_snoozing_a_firing_native_alert_ends_the_firing_and_clearing_it_removes_the_mute(self) -> None:
        configuration_id = self._create()
        with team_scope(self.team.id):
            platform_testing.start_firing(configuration_id, team_id=self.team.id, at=datetime(2026, 1, 1, tzinfo=UTC))
        until = django_timezone.now() + timedelta(hours=1)

        snoozed: list[tuple[datetime | None, tuple[str, ...]]] = []
        with patch(_DELIVER_INLINE), team_scope(self.team.id):
            for snooze_until in (until, None):
                view = platform_writes.update_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.LOGS.value],
                    configuration_id=configuration_id,
                    change=lambda current: current,
                    snooze_until=snooze_until,
                    snooze_changed=True,
                )
                assert view is not None
                snoozed.append((view.snooze_until, tuple(alert.state for alert in view.alerts)))

        assert snoozed == [(until, (PlatformAlertState.NOT_FIRING,)), (None, (PlatformAlertState.NOT_FIRING,))]

    def test_a_snooze_is_refused_for_an_alert_whose_source_keeps_a_row(self) -> None:
        with team_scope(self.team.id):
            copy = platform_testing.create_configuration(
                team_id=self.team.id,
                name="Copy",
                source_kind=SourceKind.LOGS.value,
                source_config={"row_ids": ["a"]},
                check_interval_minutes=5,
                owner=PlatformAlertOwner.PLATFORM,
                legacy_configuration_id=uuid4(),
            )
            with pytest.raises(InvalidPlatformAlertEdit):
                platform_writes.update_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.LOGS.value],
                    configuration_id=copy.id,
                    change=lambda current: current,
                    snooze_until=django_timezone.now() + timedelta(hours=1),
                    snooze_changed=True,
                )
            assert PlatformAlertConfiguration.objects.get(id=copy.id).snooze_until is None

    def test_admission_refuses_a_create_past_the_cap_and_sees_an_edit_that_turns_the_alert_on(self) -> None:
        admitted: list[tuple[bool, bool, int | None]] = []

        def admit(
            *,
            team_id: int,
            current: PlatformAlertConfigurationEdit | None,
            edit: PlatformAlertConfigurationEdit,
            check_interval_minutes: int | None,
        ) -> None:
            admitted.append((current is None, edit.enabled, check_interval_minutes))

        assert self.spec.native is not None
        capped = replace(self.spec, admit=admit, native=replace(self.spec.native, max_per_team=1))
        with patch(_SOURCE_CONFIGS, return_value=capped):
            configuration_id = self._create()
            with pytest.raises(PlatformAlertCreateRefused):
                self._create()
            with team_scope(self.team.id):
                platform_writes.update_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.LOGS.value],
                    configuration_id=configuration_id,
                    change=lambda current: replace(current, enabled=False),
                )
                platform_writes.update_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.LOGS.value],
                    configuration_id=configuration_id,
                    change=lambda current: replace(current, enabled=True),
                )

        assert admitted == [(True, True, 5), (False, True, 5)]
        assert count_configurations(team_id=self.team.id, source_kind=SourceKind.LOGS) == 1

    @parameterized.expand(
        [
            ("fixed_cadence_kind", None, None, (5, None)),
            ("fixed_cadence_kind_asked_for_another", None, 60, None),
            ("chosen_minute_cadence", {1: None, 10080: "week"}, 1, (1, None)),
            ("chosen_calendar_cadence", {1: None, 10080: "week"}, 10080, (10080, "week")),
            ("chosen_cadence_left_out", {1: None, 10080: "week"}, None, (5, None)),
            ("cadence_the_kind_lacks", {1: None, 10080: "week"}, 15, None),
        ]
    )
    def test_a_native_create_is_admitted_and_stored_at_the_cadence_it_gets(
        self,
        _name: str,
        check_intervals: dict[int, str | None] | None,
        requested: int | None,
        stored: tuple[int, str | None] | None,
    ) -> None:
        admitted: list[int | None] = []

        def admit(*, check_interval_minutes: int | None, **_: object) -> None:
            admitted.append(check_interval_minutes)

        assert self.spec.native is not None
        spec = replace(self.spec, admit=admit, native=replace(self.spec.native, check_intervals=check_intervals))
        with (
            patch(_SOURCE_CONFIGS, return_value=spec),
            team_scope(self.team.id),
            pytest.raises(InvalidPlatformAlertEdit) if stored is None else nullcontext(),
        ):
            platform_writes.create_configuration(
                team_id=self.team.id,
                source_kind=SourceKind.LOGS,
                edit=_edit(check_interval_minutes=requested),
                created_by_id=self.user.id,
            )

        with team_scope(self.team.id):
            stored_cadences = list(
                PlatformAlertConfiguration.objects.values_list("check_interval_minutes", "recurrence_unit")
            )
        assert (admitted, stored_cadences) == (
            [] if stored is None else [stored[0]],
            [] if stored is None else [stored],
        )

    @parameterized.expand([("native_kind", False), ("kind_whose_source_rows_have_a_delete_hook", True)])
    def test_deleting_a_firing_native_alert_resolves_by_its_own_id_before_its_destinations_go(
        self, _name: str, with_source_delete: bool
    ) -> None:
        configuration_id = self._create()
        with team_scope(self.team.id):
            platform_testing.start_firing(configuration_id, team_id=self.team.id, at=datetime(2026, 1, 1, tzinfo=UTC))
        calls: list[str] = []
        source_delete = MagicMock()
        spec = replace(self.spec, delete=source_delete) if with_source_delete else self.spec

        with (
            patch(_SOURCE_CONFIGS, return_value=spec),
            patch(_DELIVER_INLINE, side_effect=lambda request: calls.append(request.destination_alert_id)),
        ):
            self.remove_destinations.side_effect = lambda **_: calls.append("destinations removed")
            with team_scope(self.team.id):
                deleted = platform_writes.delete_configuration(
                    team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], configuration_id=configuration_id
                )

        assert deleted
        source_delete.assert_not_called()
        assert calls == [str(configuration_id), "destinations removed"]
        self.remove_destinations.assert_called_once_with(team_id=self.team.id, alert_id=configuration_id)
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
