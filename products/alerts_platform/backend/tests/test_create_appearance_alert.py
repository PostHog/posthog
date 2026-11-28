import pytest
from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import APPEARANCE_GROUPING, Grouping
from products.alerts_platform.backend.models import AlertDestination, PlatformAlertConfiguration


class TestCreateAppearanceAlert(BaseTest):
    def _create(
        self, *filters: str, destination: tuple[str, ...] = ("--webhook-url", "https://example.com/hook")
    ) -> None:
        call_command(
            "create_appearance_alert",
            "--team-id",
            str(self.team.id),
            "--source",
            "logs",
            "--name",
            "New api errors",
            *[arg for raw in filters for arg in ("--filter", raw)],
            *destination,
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

    @parameterized.expand(
        [
            ("a label the source does not have", "hostname=exact:web-1", ("--webhook-url", "https://example.com/hook")),
            # Refused after the configuration row is written, so only the transaction removes it.
            ("a plain http webhook", "service_name=exact:api", ("--webhook-url", "http://example.com/hook")),
            (
                "a Slack integration of no project",
                "service_name=exact:api",
                ("--slack-integration-id", "999999", "--slack-channel-id", "C0123"),
            ),
        ]
    )
    def test_a_refused_alert_creates_nothing(self, _name: str, raw_filter: str, destination: tuple[str, ...]) -> None:
        with pytest.raises(CommandError):
            self._create(raw_filter, destination=destination)

        assert not PlatformAlertConfiguration.objects.for_team(self.team.id).exists()
