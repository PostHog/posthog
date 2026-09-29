from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.event.util import bulk_create_events
from posthog.models.organization import Organization
from posthog.models.person_group_membership.sql import (
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
)
from posthog.models.team import Team

from products.customer_analytics.backend.facade.api import is_person_group_membership_ready
from products.customer_analytics.backend.logic.person_group_membership import (
    CHUNK_SIZE,
    MEMBERSHIP_TABLE,
    MembershipBackfill,
    advance_membership_backfill,
    fail_membership_backfill,
    insert_membership_window,
    membership_candidate_page,
    next_date_window,
    read_membership_config,
    sync_membership_team,
)
from products.customer_analytics.backend.models import (
    PersonGroupMembershipState,
    PersonGroupMembershipStatus,
    TeamCustomerAnalyticsConfig,
)


class TestMembershipWindows(SimpleTestCase):
    @parameterized.expand([(0, []), (1, [1]), (7, [7]), (15, [7, 7, 1])])
    def test_windows_are_bounded_and_contiguous(self, days: int, lengths: list[int]) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=days)
        cursor = start
        windows = []
        while window := next_date_window(cursor, end):
            assert window.start == cursor
            assert window.end - window.start <= CHUNK_SIZE
            windows.append((window.end - window.start).days)
            cursor = window.end
        assert cursor == end
        assert windows == lengths


class TestPersonGroupMembership(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for table in (SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE, PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE):
            sync_execute(f"TRUNCATE TABLE {table}")
            self.addCleanup(sync_execute, f"TRUNCATE TABLE {table}")
        self.config = self.team.customer_analytics_config
        self.config.account_group_type_index = 0
        self.config.save()
        self.flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.mock_flag = self.flag.start()
        self.addCleanup(self.flag.stop)

    def _state(self) -> PersonGroupMembershipState:
        return PersonGroupMembershipState.objects.for_team(self.team.id, canonical=True).get()

    def _input(self) -> MembershipBackfill:
        return MembershipBackfill(team_id=self.team.id, config_version=self._state().config_version, dry_run=False)

    def _rows(self) -> list:
        return sync_execute(
            f"SELECT team_id, group_type_index, group_key, distinct_id, min(first_seen), max(last_seen) "
            f"FROM {MEMBERSHIP_TABLE} GROUP BY team_id, group_type_index, group_key, distinct_id ORDER BY distinct_id"
        )

    def test_registry_versions_index_changes_and_disables(self) -> None:
        with time_machine.travel(timezone.now(), tick=False):
            initial = sync_membership_team(self.team.id, dry_run=False)
            assert initial.enabled and initial.changed and initial.needs_backfill
            assert self._state().status == PersonGroupMembershipStatus.PENDING_CONFIG
            repeated = sync_membership_team(self.team.id, dry_run=False)
            assert not repeated.changed
            assert repeated.config_version == initial.config_version
            self.config.account_group_type_index = 4
            self.config.save()
            changed = sync_membership_team(self.team.id, dry_run=False)
            assert changed.config_version > initial.config_version
            assert read_membership_config(self.team.id).group_type_index == 4
            self.mock_flag.return_value = False
            disabled = sync_membership_team(self.team.id, dry_run=False)
            assert disabled.config_version > changed.config_version
            assert not read_membership_config(self.team.id).enabled
            assert self._state().status == PersonGroupMembershipStatus.DISABLED
            assert not is_person_group_membership_ready(self.team.id)
            self.mock_flag.return_value = True
            enabled_again = sync_membership_team(self.team.id, dry_run=False)
            assert enabled_again.config_version > disabled.config_version
            assert self._state().historical_end is None

    @parameterized.expand([(None,), (-1,), (5,)])
    def test_unconfigured_and_invalid_indexes_disable_existing_registry(self, index: int | None) -> None:
        sync_membership_team(self.team.id, dry_run=False)
        self.config.account_group_type_index = index
        self.config.save()
        assert self.team.id in membership_candidate_page(0)
        result = sync_membership_team(self.team.id, dry_run=False)
        assert not result.enabled
        assert not read_membership_config(self.team.id).enabled
        assert self._state().status == PersonGroupMembershipStatus.DISABLED

    def test_candidates_are_paged_and_include_removed_configs(self) -> None:
        teams = [Team.objects.create(organization=self.organization) for _ in range(3)]
        for team in teams:
            TeamCustomerAnalyticsConfig.objects.update_or_create(team=team, defaults={"account_group_type_index": 0})
            sync_membership_team(team.id, dry_run=False)
        TeamCustomerAnalyticsConfig.objects.filter(team=teams[1]).delete()
        with patch("products.customer_analytics.backend.logic.person_group_membership.PAGE_SIZE", 2):
            first = membership_candidate_page(0)
            second = membership_candidate_page(first[-1])
            assert first + second == [self.team.id, *(team.id for team in teams)]
            assert membership_candidate_page(second[-1]) == []
        sync_membership_team(teams[1].id, dry_run=False)
        assert not read_membership_config(teams[1].id).enabled

    def test_dry_run_does_not_write_or_start_backfill(self) -> None:
        result = sync_membership_team(self.team.id)
        assert result.enabled and result.changed and not result.needs_backfill
        assert read_membership_config(self.team.id) is None
        assert not PersonGroupMembershipState.objects.for_team(self.team.id, canonical=True).exists()
        assert advance_membership_backfill(MembershipBackfill(team_id=self.team.id, config_version=1)).status == "done"

    @parameterized.expand([(False, 0), (False, 4), (True, 0), (True, 4)])
    def test_projection_and_overlap_are_idempotent(self, native_json: bool, index: int) -> None:
        schema = override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_json)
        schema.enable()
        self.addCleanup(schema.disable)
        now = timezone.now()
        oldest = now - timedelta(days=180)
        bulk_create_events(
            [
                {
                    "team": self.team,
                    "distinct_id": "one",
                    "event": "test",
                    "timestamp": oldest,
                    "properties": {f"$group_{index}": "acme", f"$group_{1 if index == 0 else 0}": "wrong"},
                },
                {
                    "team": self.team,
                    "distinct_id": "one",
                    "event": "test",
                    "timestamp": now,
                    "properties": {f"$group_{index}": "acme"},
                },
                {
                    "team": self.team,
                    "distinct_id": "propertyless",
                    "event": "test",
                    "timestamp": now,
                    "properties": {f"$group_{index}": "acme"},
                    "person_mode": "propertyless",
                },
                {
                    "team": self.team,
                    "distinct_id": "empty",
                    "event": "test",
                    "timestamp": now,
                    "properties": {f"$group_{index}": ""},
                },
                {
                    "team": self.team,
                    "distinct_id": "missing",
                    "event": "test",
                    "timestamp": now,
                    "properties": {"$group_2": "wrong"},
                },
            ]
        )
        window = next_date_window(oldest, oldest + timedelta(days=1))
        insert_membership_window(self.team.id, index, window)
        recent = next_date_window(now, now + timedelta(days=1))
        insert_membership_window(self.team.id, index, recent)
        insert_membership_window(self.team.id, index, window)
        insert_membership_window(self.team.id, index, recent)
        rows = self._rows()
        assert len(rows) == 1
        assert rows[0][:4] == (self.team.id, index, "acme", "one")
        assert rows[0][4].replace(tzinfo=UTC) == oldest
        assert rows[0][5].replace(tzinfo=UTC) == now

    def test_only_active_configured_teams_get_historical_membership(self) -> None:
        unconfigured = Team.objects.create(organization=self.organization)
        disabled_org = Organization.objects.create(name="Disabled customer analytics")
        disabled = Team.objects.create(organization=disabled_org)
        TeamCustomerAnalyticsConfig.objects.update_or_create(team=disabled, defaults={"account_group_type_index": 0})
        self.mock_flag.side_effect = lambda flag, distinct_id, **kwargs: distinct_id == str(self.organization.id)
        now = timezone.now()
        with time_machine.travel(now, tick=False) as clock:
            bulk_create_events(
                [
                    {
                        "team": team,
                        "event": "test",
                        "distinct_id": "person",
                        "timestamp": now - timedelta(days=180),
                        "properties": {"$group_0": "acme", "$group_4": "wrong"},
                    }
                    for team in [self.team, unconfigured, disabled]
                ]
            )
            candidates = membership_candidate_page(0)
            assert candidates == [self.team.id, disabled.id]
            for team_id in candidates:
                sync_membership_team(team_id, dry_run=False)
            clock.move_to(now + timedelta(seconds=120))
            input = self._input()
            for _ in range(40):
                if advance_membership_backfill(input).status == "done":
                    break
            assert is_person_group_membership_ready(self.team.id)
            assert not is_person_group_membership_ready(unconfigured.id)
            assert not is_person_group_membership_ready(disabled.id)
            assert [row[:4] for row in self._rows()] == [(self.team.id, 0, "acme", "person")]
            assert read_membership_config(disabled.id) is None
            assert read_membership_config(unconfigured.id) is None

    def test_environment_state_does_not_overwrite_parent_project(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.team.project, parent_team=self.team)
        TeamCustomerAnalyticsConfig.objects.update_or_create(team=child, defaults={"account_group_type_index": 4})
        sync_membership_team(self.team.id, dry_run=False)
        sync_membership_team(child.id, dry_run=False)
        assert self._state().group_type_index == 0
        assert PersonGroupMembershipState.objects.for_team(child.id, canonical=True).get().group_type_index == 4
        assert read_membership_config(child.id).group_type_index == 4
        PersonGroupMembershipState.objects.for_team(child.id, canonical=True).update(
            status=PersonGroupMembershipStatus.READY
        )
        assert is_person_group_membership_ready(child.id)
        assert not is_person_group_membership_ready(self.team.id)

    def test_backfill_resumes_and_waits_for_dictionary_before_catchup(self) -> None:
        now = timezone.now()
        with time_machine.travel(now, tick=False) as clock:
            old = now - timedelta(days=15)
            bulk_create_events(
                [
                    {
                        "team": self.team,
                        "event": "test",
                        "distinct_id": "old",
                        "timestamp": old,
                        "properties": {"$group_0": "acme", "$group_1": "wrong"},
                    },
                ]
            )
            sync_membership_team(self.team.id, dry_run=False)
            input = self._input()
            assert not is_person_group_membership_ready(self.team.id)
            assert advance_membership_backfill(input).status == "continue"
            fixed_end = self._state().historical_end
            assert self._state().status == PersonGroupMembershipStatus.BACKFILLING
            advance_membership_backfill(input)
            completed_until = self._state().next_window_start
            with patch(
                "products.customer_analytics.backend.logic.person_group_membership.sync_execute",
                side_effect=RuntimeError("CH unavailable"),
            ):
                with self.assertRaises(RuntimeError):
                    advance_membership_backfill(input)
            fail_membership_backfill(input, "RuntimeError")
            assert self._state().status == PersonGroupMembershipStatus.FAILED
            assert self._state().next_window_start == completed_until
            advance_membership_backfill(input)
            assert self._state().historical_end == fixed_end
            advance_membership_backfill(input)
            waiting = advance_membership_backfill(input)
            assert waiting.status == "waiting"
            assert waiting.wait_until == now + timedelta(seconds=120)
            assert not is_person_group_membership_ready(self.team.id)
            bulk_create_events(
                [
                    {
                        "team": self.team,
                        "event": "test",
                        "distinct_id": "late",
                        "timestamp": old - timedelta(days=1),
                        "created_at": now + timedelta(seconds=1),
                        "properties": {"$group_0": "acme"},
                    },
                ]
            )
            clock.move_to(now + timedelta(seconds=120))
            advance_membership_backfill(input)
            assert self._state().status == PersonGroupMembershipStatus.CATCHING_UP
            assert not is_person_group_membership_ready(self.team.id)
            advance_membership_backfill(input)
            assert advance_membership_backfill(input).status == "done"
            assert is_person_group_membership_ready(self.team.id)
            assert {row[3] for row in self._rows()} == {"old", "late"}
            before = self._rows()
            assert advance_membership_backfill(input).status == "done"
            assert self._rows() == before
            self.config.account_group_type_index = 1
            self.config.save()
            assert not is_person_group_membership_ready(self.team.id)
            sync_membership_team(self.team.id, dry_run=False)
            assert advance_membership_backfill(input).status == "done"
            fail_membership_backfill(input, "stale worker")
            assert self._state().status == PersonGroupMembershipStatus.PENDING_CONFIG

    @parameterized.expand([(status,) for status in PersonGroupMembershipStatus.values])
    def test_facade_readiness_fails_closed(self, status: str) -> None:
        assert not is_person_group_membership_ready(self.team.id)
        sync_membership_team(self.team.id, dry_run=False)
        PersonGroupMembershipState.objects.for_team(self.team.id, canonical=True).update(status=status)
        assert is_person_group_membership_ready(self.team.id) == (status == PersonGroupMembershipStatus.READY)
        self.mock_flag.return_value = False
        assert not is_person_group_membership_ready(self.team.id)
