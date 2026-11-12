from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection

from parameterized import parameterized

from products.alerts_platform.backend.facade.api import (
    create_alert_destinations,
    delete_alert_destinations,
    delete_source_destination_rows,
    list_alert_destinations,
    list_source_destinations,
    record_source_destination,
    set_subscriber_destinations,
    subscriber_user_ids_by_public_id,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationGroup,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    SourceDestination,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import PlatformAlertConfiguration

WEBHOOK_URL = "https://example.com/hooks/secret-path"
WEBHOOK = cast(AlertDestinationData, {"type": DestinationType.WEBHOOK, "webhook_url": WEBHOOK_URL})
FIRING = (AlertEventKind.FIRING,)
SLACK = cast(
    AlertDestinationData,
    {"type": DestinationType.SLACK, "slack_workspace_id": 7, "slack_channel_id": "C1", "slack_channel_name": "a"},
)
EVENT_IDS = ("$logs_alert_firing",)


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

    def test_subscribers_replace_only_the_destinations_that_name_users(self) -> None:
        addresses = cast(AlertDestinationData, {"type": DestinationType.EMAIL, "email_addresses": ["a@example.com"]})
        self._create(
            NewAlertDestination(data=WEBHOOK, event_kinds=FIRING),
            NewAlertDestination(data=addresses, event_kinds=FIRING),
        )
        public_id = self.configuration.id

        def subscribe(*user_ids: int) -> None:
            assert set_subscriber_destinations(
                team_id=self.team.id,
                public_id=public_id,
                user_ids=user_ids,
                event_kinds=FIRING,
                in_app_resource_type="insight",
                in_app_resource_id="abc123",
            )

        subscribe(3, 1, 3)
        subscribe(2)
        assert subscriber_user_ids_by_public_id(team_id=self.team.id, public_ids=[public_id]) == {public_id: (2,)}
        subscribe()
        assert subscriber_user_ids_by_public_id(team_id=self.team.id, public_ids=[public_id]) == {}
        assert [d.data for d in list_alert_destinations(team_id=self.team.id, configuration_id=public_id)] == [
            WEBHOOK,
            addresses,
        ]
        assert not set_subscriber_destinations(
            team_id=self.team.id,
            public_id=uuid4(),
            user_ids=[1],
            event_kinds=FIRING,
            in_app_resource_type="insight",
            in_app_resource_id="abc123",
        )

    def test_an_alert_whose_product_keeps_hog_functions_takes_rows_beside_them(self) -> None:
        configuration = self._configuration(destinations_owner=PlatformAlertOwner.SOURCE)

        self._create(NewAlertDestination(data=WEBHOOK, event_kinds=FIRING), configuration=configuration)

        assert [d.data for d in list_alert_destinations(team_id=self.team.id, configuration_id=configuration.id)] == [
            WEBHOOK
        ]

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


class TestSourceDestinations(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.legacy_id = uuid4()
        self.configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            team=self.team,
            name="API errors",
            source_kind=SourceKind.LOGS,
            check_interval_minutes=5,
            destinations_owner=PlatformAlertOwner.SOURCE,
            legacy_configuration_id=self.legacy_id,
        )
        self.groups: list[AlertDestinationGroup] = []
        resolver = patch(
            "products.alerts_platform.backend.logic.alert_destinations.list_alert_destination_groups",
            side_effect=self._groups,
        )
        resolver.start()
        self.addCleanup(resolver.stop)

    def _groups(self, *, team_id: int, alert_id: str, allowed_event_ids: Any) -> list[AlertDestinationGroup]:
        assert alert_id == str(self.legacy_id) and list(allowed_event_ids) == list(EVENT_IDS)
        return self.groups

    def _hog_functions(self, data: AlertDestinationData, count: int = 2) -> tuple[UUID, ...]:
        ids = tuple(uuid4() for _ in range(count))
        self.groups.append(AlertDestinationGroup(hog_function_ids=ids, data=data, fully_enabled=True))
        return ids

    def _record(self, data: AlertDestinationData, hog_function_ids: tuple[UUID, ...]) -> Any:
        return record_source_destination(
            team_id=self.team.id,
            public_id=self.legacy_id,
            data=data,
            event_kinds=FIRING,
            hog_function_ids=hog_function_ids,
            hog_function_event_ids=EVENT_IDS,
        )

    def _listed(self) -> tuple[SourceDestination, ...]:
        return list_source_destinations(
            team_id=self.team.id, public_id=self.legacy_id, hog_function_event_ids=EVENT_IDS
        )

    def test_a_row_that_copies_its_hog_functions_lists_once_with_both_ids(self) -> None:
        hog_function_ids = self._hog_functions(SLACK)

        created = self._record(SLACK, hog_function_ids)

        assert created.legacy_hog_function_ids == hog_function_ids
        assert self._listed() == (
            SourceDestination(destination_id=created.id, hog_function_ids=hog_function_ids, data=SLACK, enabled=True),
        )

    @parameterized.expand(
        [
            ("copies_part_of_the_group", 1),
            ("copies_none_of_it", 0),
        ]
    )
    def test_a_row_that_duplicates_a_group_it_does_not_copy_is_refused(self, _name: str, copied: int) -> None:
        hog_function_ids = self._hog_functions(SLACK)

        with pytest.raises(AlertDestinationValidationError):
            self._record(cast(AlertDestinationData, {**SLACK, "slack_channel_name": "b"}), hog_function_ids[:copied])

        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == ()

    def test_the_list_keeps_groups_no_row_copies_and_rows_whose_hog_functions_are_gone(self) -> None:
        older = self._hog_functions(WEBHOOK)
        orphan = self._record(SLACK, (uuid4(),))
        set_subscriber_destinations(
            team_id=self.team.id,
            public_id=self.legacy_id,
            user_ids=[self.user.id],
            event_kinds=FIRING,
            in_app_resource_type="insight",
            in_app_resource_id="1",
        )

        assert self._listed() == (
            SourceDestination(destination_id=None, hog_function_ids=older, data=WEBHOOK, enabled=True),
            SourceDestination(destination_id=orphan.id, hog_function_ids=(), data=SLACK, enabled=True),
        )

    def test_a_delete_by_hog_function_or_row_id_returns_the_hog_functions_the_rows_copied(self) -> None:
        slack = self._hog_functions(SLACK)
        self._record(SLACK, slack)
        webhook = self._hog_functions(WEBHOOK)
        by_id = self._record(WEBHOOK, webhook)

        copied = delete_source_destination_rows(
            team_id=self.team.id, public_id=self.legacy_id, destination_ids=[by_id.id], hog_function_ids=slack[:1]
        )

        assert copied == frozenset({*slack, *webhook})
        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == ()

    @parameterized.expand(
        [
            ("no_platform_copy", PlatformAlertOwner.SOURCE, True),
            ("platform_keeps_the_destinations", PlatformAlertOwner.PLATFORM, False),
        ]
    )
    def test_no_row_is_written_beside_the_hog_functions(self, _name: str, owner: str, unknown_alert: bool) -> None:
        self.configuration.destinations_owner = owner
        self.configuration.save()

        created = record_source_destination(
            team_id=self.team.id,
            public_id=uuid4() if unknown_alert else self.legacy_id,
            data=SLACK,
            event_kinds=FIRING,
            hog_function_ids=(uuid4(),),
            hog_function_event_ids=EVENT_IDS,
        )

        assert created is None
        assert list_alert_destinations(team_id=self.team.id, configuration_id=self.configuration.id) == ()
