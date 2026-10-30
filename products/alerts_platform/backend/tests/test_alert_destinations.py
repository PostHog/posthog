from typing import Any, cast
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest

from django.db import connection

from parameterized import parameterized

from products.alerts_platform.backend.facade.api import (
    create_alert_destinations,
    delete_alert_destinations,
    list_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import PlatformAlertConfiguration

WEBHOOK_URL = "https://example.com/hooks/secret-path"
WEBHOOK = cast(AlertDestinationData, {"type": DestinationType.WEBHOOK, "webhook_url": WEBHOOK_URL})
FIRING = (AlertEventKind.FIRING,)


class TestAlertDestinations(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.configuration = self._configuration()

    def _configuration(self, destinations_owner: str = PlatformAlertOwner.PLATFORM) -> PlatformAlertConfiguration:
        return PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            team=self.team,
            name="API errors",
            source_kind=SourceKind.LOGS,
            check_interval_minutes=5,
            destinations_owner=destinations_owner,
        )

    def _create(self, *destinations: NewAlertDestination, configuration: Any = None) -> Any:
        return create_alert_destinations(
            team_id=self.team.id,
            configuration_id=(configuration or self.configuration).id,
            destinations=destinations,
        )

    def test_a_destination_reads_back_as_written_and_its_address_is_encrypted_at_rest(self) -> None:
        legacy_id = uuid4()
        created = self._create(
            NewAlertDestination(data=WEBHOOK, event_kinds=FIRING, legacy_hog_function_ids=(legacy_id,)),
            NewAlertDestination(
                data=cast(AlertDestinationData, {**WEBHOOK, "webhook_url": "https://example.com/hooks/other"}),
                event_kinds=(AlertEventKind.FIRING, AlertEventKind.RESOLVED),
                enabled=False,
            ),
        )

        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == created
        assert [(d.enabled, d.legacy_hog_function_ids) for d in created] == [(True, (legacy_id,)), (False, ())]
        assert created[0].data["webhook_url"] == WEBHOOK_URL
        with connection.cursor() as cursor:
            cursor.execute("SELECT config::text FROM alerts_platformalertdestination")
            assert all(WEBHOOK_URL not in row[0] for row in cursor.fetchall())

    @parameterized.expand(
        [
            ("no_event", {"event_kinds": ()}, "event_kinds"),
            ("check_event", {"event_kinds": (AlertEventKind.CHECK,)}, "event_kinds"),
            (
                "plain_http_address",
                {"data": {"type": DestinationType.WEBHOOK, "webhook_url": "http://example.com/h"}},
                "config",
            ),
            ("unknown_type", {"data": {"type": "opsgenie"}}, "type"),
            ("webhook_without_its_url", {"data": {"type": DestinationType.WEBHOOK}}, "config"),
            ("webhook_url_not_text", {"data": {"type": DestinationType.WEBHOOK, "webhook_url": 123}}, "config"),
            (
                "routing_key_not_text",
                {"data": {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": 123}},
                "config",
            ),
            (
                "email_not_a_list",
                {"data": {"type": DestinationType.EMAIL, "email_addresses": "a@example.com"}},
                "config",
            ),
            ("user_id_not_a_number", {"data": {"type": DestinationType.IN_APP, "in_app_user_ids": ["1"]}}, "config"),
        ]
    )
    def test_a_refused_destination_writes_nothing_of_its_batch(
        self, _name: str, override: dict[str, Any], field: str
    ) -> None:
        valid = NewAlertDestination(data=WEBHOOK, event_kinds=FIRING)
        refused = NewAlertDestination(**{"data": WEBHOOK, "event_kinds": FIRING, **override})

        with pytest.raises(AlertDestinationValidationError) as error:
            self._create(valid, refused)

        assert error.value.field == field
        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == ()

    def test_an_alert_whose_product_holds_its_destinations_takes_none_here(self) -> None:
        configuration = self._configuration(destinations_owner=PlatformAlertOwner.SOURCE)

        with pytest.raises(AlertDestinationValidationError):
            self._create(NewAlertDestination(data=WEBHOOK, event_kinds=FIRING), configuration=configuration)

        assert list_alert_destinations(team_id=self.team.id, configuration_id=configuration.id) == ()

    @parameterized.expand(
        [
            ("same_webhook", WEBHOOK, dict(WEBHOOK)),
            (
                "same_slack_channel_with_another_label",
                {
                    "type": DestinationType.SLACK,
                    "slack_workspace_id": 7,
                    "slack_channel_id": "C1",
                    "slack_channel_name": "a",
                },
                {
                    "type": DestinationType.SLACK,
                    "slack_workspace_id": 7,
                    "slack_channel_id": "C1",
                    "slack_channel_name": "b",
                },
            ),
        ]
    )
    def test_a_destination_the_alert_already_sends_to_is_refused(
        self, _name: str, first: dict[str, Any], second: dict[str, Any]
    ) -> None:
        self._create(NewAlertDestination(data=cast(AlertDestinationData, first), event_kinds=FIRING))

        with pytest.raises(AlertDestinationValidationError) as error:
            self._create(
                NewAlertDestination(data=cast(AlertDestinationData, second), event_kinds=(AlertEventKind.RESOLVED,))
            )

        assert error.value.field == "config"
        assert len(list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id)) == 1

    def test_a_delete_reaches_only_the_alert_it_names(self) -> None:
        other = self._configuration()
        (mine,) = self._create(NewAlertDestination(data=WEBHOOK, event_kinds=FIRING))
        (theirs,) = self._create(NewAlertDestination(data=WEBHOOK, event_kinds=FIRING), configuration=other)

        deleted = delete_alert_destinations(
            team_id=self.team.id, configuration_id=self.configuration.id, destination_ids=[mine.id, theirs.id]
        )

        assert deleted == 1
        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == ()
        assert list_alert_destinations(team_id=self.team.id, configuration_id=other.id) == (theirs,)
