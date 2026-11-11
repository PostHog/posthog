from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models import Team
from posthog.taxonomy.property_last_sent import (
    LAST_SENT_MAP_STALE_AFTER,
    PropertyLastSentStatus,
    fetch_property_last_sent_map,
    get_property_last_sent_map,
    is_last_sent_tracked,
    rebuild_property_last_sent_map_in_background,
)

from products.event_definitions.backend.models import PropertyDefinition


class TestFetchPropertyLastSentMap(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # property_values keeps rows across tests, so each test writes to a team of its own.
        self.team = Team.objects.create(organization=self.organization)
        self.now = datetime.now(UTC).replace(microsecond=0)

    def _insert(self, team_id: int, property_type: str, key: str, value: str, days_ago: float) -> None:
        sync_execute(
            "INSERT INTO property_values (team_id, property_type, property_key, property_value, property_count, last_seen) VALUES",
            [(team_id, property_type, key, value, 1, self.now - timedelta(days=days_ago))],
        )

    @parameterized.expand(
        [
            ("event_keys_of_the_team", "event", True, {"$browser": 1, "plan": 12}),
            ("type_without_rows_in_an_active_team", "group_1", True, {}),
        ]
    )
    def test_rolls_up_the_latest_day_per_key(
        self, _name: str, property_type: str, has_data: bool, expected_days_ago: dict[str, int]
    ) -> None:
        self._insert(self.team.pk, "event", "$browser", "Chrome", days_ago=3)
        self._insert(self.team.pk, "event", "$browser", "Safari", days_ago=1)
        self._insert(self.team.pk, "event", "plan", "free", days_ago=12)
        self._insert(self.team.pk, "event", "legacy_flag", "on", days_ago=31)
        self._insert(self.team.pk, "person", "$browser", "Firefox", days_ago=0)
        self._insert(self.team.pk, "group_0", "industry", "retail", days_ago=2)
        self._insert(self.team.pk + 1_000_000, "event", "$browser", "Edge", days_ago=0)

        last_sent_map = fetch_property_last_sent_map(self.team, property_type, Workload.ONLINE)

        assert last_sent_map.has_data is has_data
        assert last_sent_map.too_many_keys is False
        assert {key: (self.now - at).days for key, at in last_sent_map.last_sent.items()} == expected_days_ago
        assert last_sent_map.last_sent_for("legacy_flag").status == PropertyLastSentStatus.NOT_SENT_IN_30_DAYS

    @parameterized.expand(
        [
            ("project_without_any_row", 0, None, False),
            ("type_with_too_many_keys", 3, 2, True),
        ]
    )
    def test_reports_no_dates_when_absence_proves_nothing(
        self, _name: str, key_count: int, key_cap: int | None, too_many_keys: bool
    ) -> None:
        for index in range(key_count):
            self._insert(self.team.pk, "event", f"key_{index}", "value", days_ago=1)

        with patch("posthog.taxonomy.property_last_sent.MAX_KEYS_PER_SNAPSHOT", key_cap or 100):
            last_sent_map = fetch_property_last_sent_map(self.team, "event", Workload.ONLINE)

        assert last_sent_map.too_many_keys is too_many_keys
        assert dict(last_sent_map.last_sent) == {}
        assert last_sent_map.last_sent_for("key_0").status == PropertyLastSentStatus.NOT_TRACKED


class TestIsLastSentTracked(SimpleTestCase):
    @parameterized.expand(
        [
            ("event_property", PropertyDefinition.Type.EVENT, "$browser", None, None, True),
            ("person_property", PropertyDefinition.Type.PERSON, "email", None, None, True),
            ("group_property", PropertyDefinition.Type.GROUP, "industry", 0, None, True),
            ("key_the_service_skips", PropertyDefinition.Type.EVENT, "$insert_id", None, None, False),
            ("feature_flag_key", PropertyDefinition.Type.EVENT, "$feature/new-onboarding", None, None, False),
            ("key_longer_than_the_service_keeps", PropertyDefinition.Type.EVENT, "k" * 401, None, None, False),
            ("virtual_property", PropertyDefinition.Type.EVENT, "$virt_is_bot", None, None, False),
            ("session_property", PropertyDefinition.Type.SESSION, "$session_duration", None, None, False),
            ("group_key_column", PropertyDefinition.Type.GROUP, "$group_key", 0, None, False),
            ("group_without_index", PropertyDefinition.Type.GROUP, "industry", None, None, False),
            (
                "data_warehouse_person_property",
                PropertyDefinition.Type.PERSON,
                "plan",
                None,
                {"source_id": "s", "table_name": "accounts", "column": "plan"},
                False,
            ),
        ]
    )
    def test_tracks_only_keys_the_service_records(
        self,
        _name: str,
        definition_type: int,
        name: str,
        group_type_index: int | None,
        warehouse_origin: dict | None,
        expected: bool,
    ) -> None:
        definition = PropertyDefinition(
            name=name, type=definition_type, group_type_index=group_type_index, warehouse_origin=warehouse_origin
        )

        assert is_last_sent_tracked(definition) is expected


class TestGetPropertyLastSentMap(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @patch("posthog.taxonomy.property_last_sent.refresh_property_last_sent_map.delay")
    @patch("posthog.taxonomy.property_last_sent.sync_execute")
    def test_queues_the_first_build_and_rebuilds_a_stale_map_in_the_background(
        self, mock_sync_execute, mock_delay
    ) -> None:
        with time_machine.travel(datetime(2026, 11, 1, 12, 0, tzinfo=UTC), tick=False) as traveller:
            assert get_property_last_sent_map(self.team, "event") is None
            assert get_property_last_sent_map(self.team, "event") is None
            mock_delay.assert_called_once_with(self.team.pk, "event")
            mock_sync_execute.assert_not_called()

            mock_sync_execute.return_value = [("$browser", datetime(2026, 10, 30, 8, 0))]
            rebuild_property_last_sent_map_in_background(self.team.pk, "event")
            built = get_property_last_sent_map(self.team, "event")
            assert built is not None
            assert built.last_sent_for("$browser").at == datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
            assert mock_sync_execute.call_args.kwargs["workload"] == Workload.OFFLINE
            assert mock_delay.call_count == 1

            traveller.shift(LAST_SENT_MAP_STALE_AFTER + timedelta(minutes=1))
            assert get_property_last_sent_map(self.team, "event") == built
            assert get_property_last_sent_map(self.team, "event") == built
            assert mock_delay.call_count == 2
            assert get_property_last_sent_map(self.team, "person") is None
            assert mock_delay.call_args.args == (self.team.pk, "person")
