from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from pydantic import BaseModel, ConfigDict

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.contracts import (
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    OrganizationAlertSettings,
    PlatformAlertNotEditable,
    SourceConfigSpec,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import PlatformAlertConfiguration

_SOURCE_CONFIGS = "products.alerts_platform.backend.logic.source_configs.spec"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


class _SpendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str


SETTINGS = OrganizationAlertSettings(name="Spend", enabled=True, source_config={"metric": "current"})


class TestOrganizationAlerts(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        spec = SourceConfigSpec(
            model=_SpendConfig,
            validate=lambda edit: None,
            native=NativeAlertLifecycle(check_interval_minutes=60, platform_destinations=True),
        )
        patcher = patch(_SOURCE_CONFIGS, return_value=spec)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.enterContext(time_machine.travel(NOW, tick=False))

    def _create(self) -> UUID:
        return platform_api.create_organization_configuration(
            organization_id=self.organization.id,
            team_id=self.team.id,
            source_kind=SourceKind.BILLING,
            settings=SETTINGS,
            created_by_id=self.user.id,
        ).id

    def test_a_create_stores_the_organization_defaults_on_the_home_team(self) -> None:
        configuration_id = self._create()

        stored = PlatformAlertConfiguration.objects.unscoped().get(id=configuration_id)
        assert (
            stored.team_id,
            stored.owner,
            stored.legacy_configuration_id,
            stored.check_interval_minutes,
            stored.cooldown_minutes,
            stored.next_check_at,
        ) == (self.team.id, PlatformAlertOwner.PLATFORM, None, 60, 0, NOW)

    def test_a_create_refuses_a_team_in_another_organization(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")

        with pytest.raises(InvalidPlatformAlertEdit):
            platform_api.create_organization_configuration(
                organization_id=self.organization.id,
                team_id=other_team.id,
                source_kind=SourceKind.BILLING,
                settings=SETTINGS,
                created_by_id=self.user.id,
            )

        assert not PlatformAlertConfiguration.objects.unscoped().filter(team=other_team).exists()

    @parameterized.expand([("past", timedelta(minutes=-1)), ("past_the_cap", timedelta(days=31))])
    def test_a_mute_refuses_an_end_outside_the_window(self, _name: str, offset: timedelta) -> None:
        configuration_id = self._create()

        with pytest.raises(InvalidPlatformAlertEdit):
            platform_api.mute_organization_configuration(
                organization_id=self.organization.id,
                source_kind=SourceKind.BILLING,
                configuration_id=configuration_id,
                until=NOW + offset,
            )

        assert PlatformAlertConfiguration.objects.unscoped().get(id=configuration_id).snooze_until is None

    def test_a_project_scoped_kind_is_refused(self) -> None:
        with pytest.raises(PlatformAlertNotEditable):
            platform_api.list_organization_configurations(
                organization_id=self.organization.id, source_kind=SourceKind.LOGS, limit=10, offset=0
            )

    def test_the_organization_reads_and_writes_an_alert_on_any_of_its_teams(self) -> None:
        configuration_id = self._create()
        organization_id = self.organization.id
        kind = SourceKind.BILLING

        page = platform_api.list_organization_configurations(
            organization_id=organization_id, source_kind=kind, limit=10, offset=0
        )
        updated = platform_api.update_organization_configuration(
            organization_id=organization_id,
            source_kind=kind,
            configuration_id=configuration_id,
            change=lambda current: replace(current, name="Projected spend", source_config={"metric": "projected"}),
        )
        muted = platform_api.mute_organization_configuration(
            organization_id=organization_id,
            source_kind=kind,
            configuration_id=configuration_id,
            until=NOW + timedelta(days=1),
        )

        assert [configuration.id for configuration in page.configurations] == [configuration_id]
        assert updated is not None and muted is not None
        assert (updated.name, updated.source_config, updated.cooldown_minutes) == (
            "Projected spend",
            {"metric": "projected"},
            0,
        )
        assert muted.snooze_until == NOW + timedelta(days=1)
        assert platform_api.delete_organization_configuration(
            organization_id=organization_id, source_kind=kind, configuration_id=configuration_id
        )
        assert not PlatformAlertConfiguration.objects.unscoped().filter(id=configuration_id).exists()
        assert not ActivityLog.objects.filter(
            scope="PlatformAlertConfiguration", item_id=str(configuration_id)
        ).exists()

    @parameterized.expand(
        [
            ("get", lambda org, id: platform_api.get_organization_configuration(**_address(org, id))),
            (
                "update",
                lambda org, id: platform_api.update_organization_configuration(
                    **_address(org, id), change=lambda current: replace(current, name="Taken over")
                ),
            ),
            (
                "mute",
                lambda org, id: platform_api.mute_organization_configuration(
                    **_address(org, id), until=NOW + timedelta(days=1)
                ),
            ),
            ("delete", lambda org, id: platform_api.delete_organization_configuration(**_address(org, id))),
        ]
    )
    def test_another_organization_cannot_reach_the_alert(self, _name: str, call: Any) -> None:
        configuration_id = self._create()
        other_organization = Organization.objects.create(name="Other")

        result = call(other_organization.id, configuration_id)
        page = platform_api.list_organization_configurations(
            organization_id=other_organization.id, source_kind=SourceKind.BILLING, limit=10, offset=0
        )

        assert not result
        assert page.total == 0
        stored = PlatformAlertConfiguration.objects.unscoped().get(id=configuration_id)
        assert (stored.name, stored.snooze_until) == ("Spend", None)


def _address(organization_id: UUID, configuration_id: UUID) -> dict[str, Any]:
    return {"organization_id": organization_id, "source_kind": SourceKind.BILLING, "configuration_id": configuration_id}
