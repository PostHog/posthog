import pytest
from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command

from products.alerts_platform.backend.facade.contracts import APPEARANCE_GROUPING, Grouping
from products.alerts_platform.backend.models import AlertDestination, PlatformAlertConfiguration


class TestCreateAppearanceAlert(BaseTest):
    def _create(self, *filters: str) -> None:
        call_command(
            "create_appearance_alert",
            "--team-id",
            str(self.team.id),
            "--source",
            "logs",
            "--name",
            "New api errors",
            *[arg for raw in filters for arg in ("--filter", raw)],
            "--webhook-url",
            "https://example.com/hook",
        )

    def test_creates_a_platform_owned_alert_grouped_by_identity_with_its_destination(self) -> None:
        self._create("service_name=exact:api", "severity_text=exact:error,fatal")

        configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).get()
        assert (configuration.owner, configuration.alert_kind, configuration.legacy_configuration_id) == (
            PlatformAlertConfiguration.Owner.PLATFORM,
            PlatformAlertConfiguration.Kind.APPEARANCE,
            None,
        )
        assert Grouping.from_stored(configuration.grouping).splits_like(APPEARANCE_GROUPING)
        assert configuration.source_config["filters"][1] == {
            "key": "severity_text",
            "operator": "exact",
            "values": ["error", "fatal"],
        }
        assert AlertDestination.objects.for_team(self.team.id).filter(configuration=configuration).count() == 1

    def test_a_filter_on_a_label_the_source_does_not_have_creates_nothing(self) -> None:
        with pytest.raises(CommandError):
            self._create("hostname=exact:web-1")

        assert not PlatformAlertConfiguration.objects.for_team(self.team.id).exists()
