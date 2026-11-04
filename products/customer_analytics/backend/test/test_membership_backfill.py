from collections.abc import Mapping
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from typing import Literal, cast
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.api.team.team_config import TeamCustomerAnalyticsConfigSerializer
from posthog.models import Organization, Team
from posthog.models.event.util import create_event, events_only_in_active_schema
from posthog.models.group.util import raw_create_group_ch
from posthog.redis import get_client as get_redis_client
from posthog.test.persons import create_person

from products.customer_analytics.backend.logic.feature_gate import is_customer_analytics_active
from products.customer_analytics.backend.logic.membership_backfill import (
    BATCH_SIZE,
    MembershipBackfillService,
    MembershipCursor,
    MembershipReadiness,
    MembershipRow,
    MembershipState,
    MembershipStep,
    MembershipTeam,
    get_historical_window_start,
    get_membership_batch_sql,
    get_membership_group_type_index,
    get_membership_readiness,
    get_window_end,
)
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig

MODULE = "products.customer_analytics.backend.logic.membership_backfill"
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=2)


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(hours=3), timedelta(days=1), timedelta(days=40)])
def test_date_windows_have_no_gap_or_overlap(duration: timedelta) -> None:
    cursor = START
    ends = []
    while cursor < START + duration:
        end = get_window_end(cursor, START + duration)
        assert timedelta(0) < end - cursor <= timedelta(days=1)
        ends.append(end)
        cursor = end
    assert cursor == START + duration
    assert ends == sorted(set(ends))


@pytest.mark.parametrize("days", [0, 1, 90, 91, 270])
def test_historical_windows_cover_history_backwards(days: int) -> None:
    cursor = START + timedelta(days=days)
    while cursor > START:
        start = get_historical_window_start(START, cursor)
        assert timedelta(0) < cursor - start <= timedelta(days=90)
        cursor = start
    assert cursor == START


@pytest.mark.parametrize("catching_up", [False, True])
@pytest.mark.parametrize("native_json", [False, True])
@pytest.mark.parametrize("group_type_index", [0, 1, 4])
def test_batch_projection_is_scoped_and_bounded(catching_up: bool, native_json: bool, group_type_index: int) -> None:
    sql = get_membership_batch_sql(group_type_index=group_type_index, catching_up=catching_up, native_json=native_json)
    group_column = f"properties.`$group_{group_type_index}`" if native_json else f"`$group_{group_type_index}`"
    assert "JSONExtract" not in sql
    assert "toJSONString" not in sql
    assert "team_id = %(team_id)s" in sql
    assert "person_mode != 'propertyless'" in sql
    if catching_up:
        assert f"{group_column} AS group_key" in sql
        assert "notEmpty(group_key)" in sql
        assert f"LIMIT {BATCH_SIZE}" in sql
    else:
        assert f"{group_column} = %(group_key)s" in sql
        assert "PREWHERE team_id = %(team_id)s" in sql
        assert f"LIMIT {BATCH_SIZE}" in sql
        assert "distinct_id > %(last_distinct_id)s" in sql
        assert "(inserted_at IS NULL OR inserted_at < %(snapshot_end)s)" in sql
    assert "min(timestamp), max(timestamp)" in sql
    assert ("inserted_at >=" in sql) == catching_up
    assert ("FROM events_json" in sql) == native_json


@pytest.mark.parametrize(("deadline", "expected_timeout"), [(None, 120), (25.0, 15), (310.0, 120)])
def test_query_inherits_shared_resources_and_respects_deadline(deadline: float | None, expected_timeout: int) -> None:
    service = MembershipBackfillService(deadline=deadline)
    with (
        patch(f"{MODULE}.sync_execute", return_value=[(1,)]) as execute,
        patch(f"{MODULE}.monotonic", return_value=10.0),
    ):
        assert service.query("SELECT 1", {}, team_id=17) == [(1,)]

    execute.assert_called_once()
    query_settings = cast(dict[str, int | str], execute.call_args.kwargs["settings"])
    assert "max_memory_usage" not in query_settings
    assert "max_threads" not in query_settings
    assert query_settings["max_execution_time"] == expected_timeout


@pytest.mark.parametrize("enabled", [False, True, None])
def test_shared_gate_uses_organization_identity(enabled: bool | None) -> None:
    team = Team(id=7, organization_id="00000000-0000-4000-8000-000000000001")
    with patch("posthoganalytics.feature_enabled", return_value=enabled) as gate:
        assert is_customer_analytics_active(team) is bool(enabled)
    gate.assert_called_once_with(
        "customer-analytics-csp",
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def test_lost_activity_lease_stops_the_attempt() -> None:
    team_id = 17
    key = f"customer_analytics:membership_backfill:{team_id}"

    def process_batch(service: MembershipBackfillService, _input: MembershipTeam) -> MembershipStep:
        get_redis_client(socket_timeout=2, socket_connect_timeout=2).delete(key)
        service.check_attempt()
        return MembershipStep(status="backfilling")

    with (
        patch.object(MembershipBackfillService, "process_batch", autospec=True, side_effect=process_batch),
        pytest.raises(RuntimeError, match="attempt expired"),
    ):
        MembershipBackfillService.process_activity_batch(
            MembershipTeam(team_id=team_id), deadline=float("inf"), should_stop=lambda: False
        )


class TestMembershipBackfill(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.config, _ = TeamCustomerAnalyticsConfig.objects.get_or_create(team=self.team)
        self.config.account_group_type_index = 0
        self.config.save(update_fields=["account_group_type_index"])
        self.gate = patch(f"{MODULE}.is_customer_analytics_active", return_value=True)
        self.gate.start()
        self.addCleanup(self.gate.stop)
        self.service = MembershipBackfillService()

    @staticmethod
    def get_state(team_id: int) -> MembershipState:
        config = TeamCustomerAnalyticsConfig.objects.get(team_id=team_id)
        return MembershipState.model_validate(config.properties["membership"])

    def create_state(
        self,
        *,
        historical_start: datetime = START,
        historical_end: datetime = END,
        next_window_start: datetime = START,
        next_window_end: datetime | None = END,
        current_group_key: str = "account-a",
        last_group_key: str = "",
        catch_up_end: datetime | None = None,
        account_keys: tuple[str, ...] = (),
        dry_run: bool = False,
        snapshot_end: datetime | None = None,
    ) -> MembershipCursor:
        self.config.refresh_from_db()
        self.config.properties["membership"] = MembershipState(
            group_type_index=0, version=1, status=MembershipReadiness.BACKFILLING
        ).model_dump(mode="json")
        self.config.save(update_fields=["properties"])
        return MembershipCursor(
            team_id=self.team.id,
            group_type_index=0,
            version=1,
            historical_start=historical_start,
            historical_end=historical_end,
            next_window_start=next_window_start,
            next_window_end=next_window_end,
            current_group_key=current_group_key,
            last_group_key=last_group_key,
            catch_up_end=catch_up_end,
            account_keys=account_keys,
            dry_run=dry_run,
            snapshot_end=snapshot_end,
        )

    def process_batch(self, state: MembershipCursor) -> MembershipStep:
        result = self.service.process_batch(
            MembershipTeam(
                team_id=state.team_id,
                version=state.version,
                account_keys=state.account_keys,
                dry_run=state.dry_run,
                cursor=state,
            )
        )
        if result.cursor:
            for field in fields(state):
                setattr(state, field.name, getattr(result.cursor, field.name))
        return result

    def test_eligibility_uses_shared_gate_and_valid_index(self) -> None:
        for index in (None, -1, 0, 4, 5):
            self.config.account_group_type_index = index
            self.config.save(update_fields=["account_group_type_index"])
            for active in (False, True):
                with patch(f"{MODULE}.is_customer_analytics_active", return_value=active):
                    assert get_membership_group_type_index(self.team) == (index if active and index in (0, 4) else None)

    def test_registry_versions_change_only_for_configuration_changes(self) -> None:
        self.config.properties = {"other": {"enabled": True}, "membership": {"future_key": "keep"}}
        self.config.save(update_fields=["properties"])
        with patch.object(self.service, "write_registry"):
            first = self.service.sync_team(self.team, 0, None)
            second = self.service.sync_team(self.team, 0, (0, 1, first.version))
            changed = self.service.sync_team(self.team, 3, (0, 1, first.version))
            disabled = self.service.sync_team(self.team, None, (3, 1, changed.version))
        assert first.version == second.version
        assert changed.version > first.version
        assert changed.group_type_index == 3
        assert disabled.version > changed.version
        assert disabled.status == MembershipReadiness.DISABLED
        self.config.refresh_from_db()
        assert self.config.properties["other"] == {"enabled": True}
        assert self.config.properties["membership"]["future_key"] == "keep"

    def test_registry_write_failure_can_resume(self) -> None:
        with patch.object(self.service, "write_registry", side_effect=RuntimeError("Unavailable")):
            with pytest.raises(RuntimeError):
                self.service.sync_team(self.team, 0, None)
        pending = self.get_state(self.team.id)
        with patch.object(self.service, "write_registry"):
            recovered = self.service.sync_team(self.team, 0, (0, 1, pending.version))
        assert recovered.version == pending.version
        assert self.get_state(self.team.id).synced_at is not None

    @parameterized.expand([("registry",), ("progress",), ("failure",)])
    def test_membership_updates_preserve_other_properties(self, operation: str) -> None:
        state = self.create_state()
        stale_config = TeamCustomerAnalyticsConfig.objects.get(team_id=self.team.id)
        synced_at = timezone.now().isoformat()

        def update_other_properties(*args: object) -> None:
            config = TeamCustomerAnalyticsConfig.objects.get(team_id=self.team.id)
            config.properties["other"] = {"enabled": True}
            config.properties["membership"]["future_key"] = "keep"
            config.properties["membership"]["synced_at"] = synced_at
            config.save(update_fields=["properties"])

        if operation == "registry":
            with patch.object(self.service, "write_registry", side_effect=update_other_properties):
                self.service.sync_team(self.team, 0, (0, 1, state.version))
        else:
            update_other_properties()
            if operation == "progress":
                state.status = MembershipReadiness.CATCHING_UP
                self.service.save_progress(state)
            else:
                self.service.fail(self.team.id, state.version, "Unavailable")

        serializer = TeamCustomerAnalyticsConfigSerializer(
            stale_config, data={"activity_event": {"event": "$pageview"}}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.config.refresh_from_db()
        assert self.config.properties["other"] == {"enabled": True}
        assert self.config.properties["membership"]["future_key"] == "keep"
        membership = self.get_state(self.team.id)
        assert membership.synced_at is not None
        if operation != "registry":
            assert membership.synced_at.isoformat() == synced_at
        assert (
            membership.status
            == {
                "registry": MembershipReadiness.BACKFILLING,
                "progress": MembershipReadiness.CATCHING_UP,
                "failure": MembershipReadiness.FAILED,
            }[operation]
        )

    def test_coordinator_registry_and_disable(self) -> None:
        disabled_team = Team.objects.create(organization=Organization.objects.create(name="Disabled organization"))
        disabled_config, _ = TeamCustomerAnalyticsConfig.objects.get_or_create(team=disabled_team)
        disabled_config.account_group_type_index = 2
        disabled_config.save(update_fields=["account_group_type_index"])
        unconfigured_team = Team.objects.create(organization=self.organization)
        TeamCustomerAnalyticsConfig.objects.get_or_create(team=unconfigured_team)
        with patch(f"{MODULE}.is_customer_analytics_active", side_effect=lambda team, **_: team.id != disabled_team.id):
            dry_run = self.service.sync_page(0, dry_run=True)
            assert dry_run.teams == ()
            assert "membership" not in TeamCustomerAnalyticsConfig.objects.get(team_id=self.team.id).properties
            page = self.service.sync_page(0, dry_run=False)
            assert [team.team_id for team in page.teams] == [self.team.id]
            assert self.service.query(
                "SELECT team_id FROM distributed_person_group_membership_config GROUP BY team_id HAVING argMax(enabled, version) = 1",
                {},
            ) == [(self.team.id,)]
            self.service.query("SYSTEM RELOAD DICTIONARY person_group_membership_config_dict", {})
            assert self.service.dictionary_visible(self.team.id, 0)
            assert not self.service.dictionary_visible(disabled_team.id, 2)
            self.config.account_group_type_index = None
            self.config.save(update_fields=["account_group_type_index"])
            assert self.service.sync_page(0, dry_run=False).teams == ()
            assert (
                self.service.query(
                    "SELECT team_id FROM distributed_person_group_membership_config GROUP BY team_id HAVING argMax(enabled, version) = 1",
                    {},
                )
                == []
            )
            self.service.query("SYSTEM RELOAD DICTIONARY person_group_membership_config_dict", {})
            assert not self.service.dictionary_visible(self.team.id, 0)
        assert get_membership_readiness(self.team) == "pending_config"

    def test_coordinator_batches_configuration_reads_and_organization_flags(self) -> None:
        sibling = Team.objects.create(organization=self.organization)
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        other = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        for team in (sibling, other):
            config, _ = TeamCustomerAnalyticsConfig.objects.get_or_create(team=team)
            config.account_group_type_index = 4
            config.save(update_fields=["account_group_type_index"])
        with (
            patch.object(self.service, "query", return_value=[]),
            patch(f"{MODULE}.is_customer_analytics_active", return_value=True) as gate,
            self.assertNumQueries(3),
        ):
            page = self.service.sync_page(0, dry_run=True)
        assert page.candidates == page.enabled == 4
        assert gate.call_count == 2
        assert {call.args[0].organization_id for call in gate.call_args_list} == {
            self.organization.id,
            other.organization_id,
        }
        assert not TeamCustomerAnalyticsConfig.objects.filter(team_id=child.id).exists()
        with patch(f"{MODULE}.PAGE_SIZE", 1):
            page = self.service.sync_page(child.id - 1, dry_run=False)
        assert [team.team_id for team in page.teams] == [child.id]
        assert page.next_team_id == child.id
        assert self.get_state(child.id).group_type_index == 0

    @parameterized.expand([("cancelled",), ("expired",)])
    def test_coordinator_stops_before_registry_writes(self, reason: str) -> None:
        stopped = False
        service = MembershipBackfillService(should_stop=lambda: stopped)

        def stop_during_flag_check(*args: object, **kwargs: object) -> bool:
            nonlocal stopped
            if reason == "expired":
                service.deadline = 0
            else:
                stopped = True
            return True

        with (
            patch(f"{MODULE}.is_customer_analytics_active", side_effect=stop_during_flag_check),
            pytest.raises(RuntimeError, match="attempt expired"),
        ):
            service.sync_page(0, dry_run=False)
        self.config.refresh_from_db()
        assert "membership" not in self.config.properties
        assert self.service.query(
            "SELECT count() FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
        ) == [(0,)]

    @parameterized.expand([("registry",), ("planning",)])
    def test_prepared_version_marks_initial_batch_failed(self, failure: str) -> None:
        prepared = self.service.prepare_backfill(MembershipTeam(team_id=self.team.id))
        assert prepared.version > 0
        assert prepared.version == self.get_state(self.team.id).version
        query = self.service.query

        def fail_query(
            sql: str, params: Mapping[str, object] | list[tuple[object, ...]], *, team_id: int | None = None
        ) -> list[tuple[object, ...]]:
            if (failure == "registry" and sql.startswith("INSERT")) or (
                failure == "planning" and "ORDER BY event_date" in sql
            ):
                raise RuntimeError("Unavailable")
            return query(sql, params, team_id=team_id)

        with patch.object(self.service, "query", side_effect=fail_query):
            with pytest.raises(RuntimeError, match="Unavailable"):
                self.service.process_batch(prepared)
        self.service.fail(self.team.id, prepared.version, "Unavailable")
        assert self.get_state(self.team.id).status == MembershipReadiness.FAILED
        assert self.get_state(self.team.id).version == prepared.version

    def test_unknown_flag_keeps_registry_and_cursor(self) -> None:
        state = self.create_state()
        self.service.write_registry(self.team.id, 0, True, state.version)
        with (
            patch(f"{MODULE}.is_customer_analytics_active", wraps=is_customer_analytics_active),
            patch("posthoganalytics.feature_enabled", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="flag evaluation is unavailable"):
                self.service.sync_page(0, dry_run=False)
            with pytest.raises(RuntimeError, match="flag evaluation is unavailable"):
                self.process_batch(state)
        config = self.get_state(self.team.id)
        assert config.status == MembershipReadiness.BACKFILLING
        assert config.version == state.version
        assert state.next_window_end == END
        assert self.service.query(
            "SELECT argMax(enabled, version) FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
        ) == [(1,)]

    def test_child_environment_has_its_own_configuration_and_memberships(self) -> None:
        parent = self.create_state()
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        with patch.object(self.service, "write_registry"):
            child_config = self.service.sync_team(child, 0, None)
        assert self.get_state(child.id).version == child_config.version
        assert get_membership_group_type_index(child) == 0
        with self.assertNumQueries(1):
            active = self.service.get_active_state(child.id, child_config.version)
        assert active is not None and active.version == child_config.version
        child_cursor = MembershipCursor(team_id=child.id, group_type_index=0, version=child_config.version)
        with patch(
            f"{MODULE}.get_persons_mapped_by_distinct_id",
            return_value={"identified": SimpleNamespace(is_identified=True)},
        ):
            assert (
                self.service.insert_memberships(
                    child_cursor,
                    [MembershipRow(distinct_id="identified", group_key="account-a", first_seen=START, last_seen=END)],
                )
                == 1
            )
        assert self.service.query(
            "SELECT team_id FROM person_group_membership WHERE team_id IN %(team_ids)s GROUP BY team_id",
            {"team_ids": [self.team.id, child.id]},
        ) == [(child.id,)]
        assert self.get_state(self.team.id).version == parent.version
        assert self.get_state(child.id).version == child_config.version

    @parameterized.expand([("cancelled",), ("expired",)])
    def test_stopped_attempt_cannot_write_or_advance(self, reason: str) -> None:
        state = self.create_state()
        stopped = False
        service = MembershipBackfillService(should_stop=lambda: stopped)

        def get_persons(*args: object, **kwargs: object) -> dict[str, SimpleNamespace]:
            nonlocal stopped
            if reason == "cancelled":
                stopped = True
            else:
                service.deadline = 0
            return {"identified": SimpleNamespace(is_identified=True)}

        with (
            patch.object(service, "query", return_value=[("identified", "account-a", START, END)]),
            patch(f"{MODULE}.get_persons_mapped_by_distinct_id", side_effect=get_persons),
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
            pytest.raises(RuntimeError, match="attempt expired"),
        ):
            service.process_batch(MembershipTeam(team_id=self.team.id, version=state.version, cursor=state))
        assert state.next_window_end == END
        assert state.rows_written == 0
        assert self.service.query(
            "SELECT count() FROM person_group_membership WHERE team_id = %(team_id)s", {"team_id": self.team.id}
        ) == [(0,)]

    @parameterized.expand([("version",), ("disabled",)])
    def test_stale_cursor_cannot_replace_newer_configuration(self, change: str) -> None:
        state = self.create_state()
        self.config.refresh_from_db()
        if change == "version":
            self.config.properties["membership"]["version"] = 2
        else:
            self.config.properties["membership"]["status"] = MembershipReadiness.DISABLED
        expected = dict(self.config.properties["membership"])
        self.config.save(update_fields=["properties"])
        with pytest.raises(RuntimeError, match="configuration changed"):
            self.service.save_progress(state)
        assert self.process_batch(state).status == "disabled"
        self.service.fail(self.team.id, state.version, "Unavailable")
        self.config.refresh_from_db()
        assert self.config.properties["membership"] == expected

    def test_identity_failure_does_not_advance_the_cursor(self) -> None:
        state = self.create_state()
        with (
            patch.object(self.service, "query", return_value=[("person-a", "account-a", START, START)]),
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
            patch(f"{MODULE}.get_persons_mapped_by_distinct_id", side_effect=RuntimeError("Unavailable")),
        ):
            with pytest.raises(RuntimeError, match="Unavailable"):
                self.process_batch(state)
        assert state.next_window_start == START
        assert state.last_distinct_id == ""

    def test_insert_admits_only_current_identified_profiles(self) -> None:
        state = self.create_state()
        rows = [
            MembershipRow(distinct_id=key, group_key="account-a", first_seen=START, last_seen=END)
            for key in ("identified", "anonymous", "deleted", "missing")
        ]
        persons = {"identified": SimpleNamespace(is_identified=True), "anonymous": SimpleNamespace(is_identified=False)}
        with (
            patch(f"{MODULE}.get_persons_mapped_by_distinct_id", return_value=persons),
            patch.object(self.service, "query") as query,
        ):
            assert self.service.insert_memberships(state, rows) == 1
        assert query.call_args.args[1] == [(self.team.id, 0, "account-a", "identified", START, END)]

    def test_batch_eligibility_uses_two_reads_and_rechecks_the_flag(self) -> None:
        state = self.create_state(account_keys=("account-a",))
        with (
            patch.object(self.service, "query", side_effect=[[("identified", "account-a", START, END)], []]),
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
            patch(
                f"{MODULE}.get_persons_mapped_by_distinct_id",
                return_value={"identified": SimpleNamespace(is_identified=True)},
            ),
            patch(f"{MODULE}.is_customer_analytics_active", return_value=True) as gate,
            self.assertNumQueries(2),
        ):
            assert self.process_batch(state).rows == 1
        assert gate.call_count == 2

    @parameterized.expand([("index",), ("version",), ("flag",)])
    def test_batch_rechecks_eligibility_before_writing(self, change: str) -> None:
        state = self.create_state(account_keys=("account-a",))
        with patch(f"{MODULE}.is_customer_analytics_active", return_value=True) as gate:

            def get_persons(*args: object, **kwargs: object) -> dict[str, SimpleNamespace]:
                if change == "index":
                    self.config.account_group_type_index = 1
                    self.config.save(update_fields=["account_group_type_index"])
                elif change == "version":
                    self.config.refresh_from_db()
                    self.config.properties["membership"]["version"] = state.version + 1
                    self.config.save(update_fields=["properties"])
                else:
                    gate.return_value = False
                return {"identified": SimpleNamespace(is_identified=True)}

            with (
                patch.object(self.service, "query", return_value=[("identified", "account-a", START, END)]) as query,
                patch(f"{MODULE}.use_new_events_schema", return_value=False),
                patch(f"{MODULE}.get_persons_mapped_by_distinct_id", side_effect=get_persons),
            ):
                assert self.process_batch(state).rows == 0
            query.assert_called_once()

    def test_failed_batch_resumes_from_the_last_committed_window(self) -> None:
        state = self.create_state(
            historical_end=START + timedelta(days=270), next_window_end=START + timedelta(days=270)
        )
        with (
            patch.object(self.service, "query", return_value=[]),
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
        ):
            assert self.process_batch(state).status == "backfilling"
            self.service.fail(self.team.id, state.version, "Unavailable")
            assert self.process_batch(state).status == "backfilling"
        assert state.next_window_end == START + timedelta(days=90)
        assert state.current_group_key == "account-a"
        assert state.error_type == ""

    def test_readiness_waits_for_dictionary_and_catch_up(self) -> None:
        state = self.create_state(
            next_window_start=END, current_group_key="", last_group_key="account-a", next_window_end=None
        )
        with patch.object(self.service, "dictionary_visible", return_value=False):
            assert self.process_batch(state).status == "waiting_for_dictionary"
        assert get_membership_readiness(self.team) == "catching_up"
        with (
            patch.object(self.service, "dictionary_visible", return_value=True),
            patch(f"{MODULE}.timezone.now", return_value=END + timedelta(minutes=10)),
        ):
            assert self.process_batch(state).status == "catching_up"
        assert state.catch_up_end == END + timedelta(minutes=10)
        assert state.next_window_start is not None
        assert state.next_window_start < END
        with (
            patch.object(self.service, "query", return_value=[]),
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
        ):
            self.process_batch(state)
        with patch.object(self.service, "dictionary_visible", return_value=True):
            assert self.process_batch(state).status == "ready"
        assert get_membership_readiness(self.team) == "ready"

    def test_disabled_and_changed_configs_stop_work(self) -> None:
        state = self.create_state()
        for index in (None, 2):
            self.config.account_group_type_index = index
            self.config.save(update_fields=["account_group_type_index"])
            assert self.process_batch(state).status == "disabled"
        assert state.next_window_start == START

    def test_planning_command_stops_at_its_deadline(self) -> None:
        clock = 1000.0
        end = timezone.now()

        def execute(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
            nonlocal clock
            sql = cast(str, args[0])
            if "ORDER BY event_date ASC" in sql:
                return [((end - timedelta(days=3650)).date(),)]
            if "ORDER BY event_date DESC" in sql:
                return [(end.date(),)]
            clock += 301
            return [(None, None, 0)]

        output = StringIO()
        with (
            patch(
                "products.customer_analytics.backend.management.commands.plan_membership_backfill.monotonic",
                return_value=clock,
            ),
            patch(f"{MODULE}.monotonic", side_effect=lambda: clock),
            patch(f"{MODULE}.sync_execute", side_effect=execute) as query,
            pytest.raises(RuntimeError, match="attempt expired"),
        ):
            call_command("plan_membership_backfill", team_id=self.team.id, stdout=output)
        assert query.call_count == 3
        assert output.getvalue() == ""

    @parameterized.expand([(False,), (True,)])
    def test_backfill_sql_admission_and_overlap(self, native_json: bool) -> None:
        start = timezone.now() - timedelta(days=100)
        end = start + timedelta(hours=1)
        state = self.create_state(
            historical_start=start,
            historical_end=end,
            next_window_start=start,
            next_window_end=end,
            snapshot_end=timezone.now() + timedelta(minutes=1),
        )
        create_person(team=self.team, distinct_ids=["identified"], is_identified=True)
        create_person(team=self.team, distinct_ids=["anonymous"], is_identified=False)
        with (
            patch(f"{MODULE}.use_new_events_schema", return_value=native_json),
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_json),
            events_only_in_active_schema(),
        ):
            events: list[tuple[str, Literal["full", "propertyless"], dict[str, str]]] = [
                ("identified", "full", {"$group_0": "account-a", "$group_1": "other-account"}),
                ("identified", "propertyless", {"$group_0": "personless-account"}),
                ("anonymous", "full", {"$group_0": "account-a"}),
                ("missing", "full", {"$group_0": "account-a"}),
                ("identified", "full", {"$group_1": "wrong-index"}),
                ("identified", "full", {"$group_0": ""}),
            ]
            for distinct_id, mode, properties in events:
                create_event(
                    event_uuid=uuid4(),
                    event="example_action",
                    team=self.team,
                    distinct_id=distinct_id,
                    person_mode=mode,
                    properties=properties,
                    timestamp=start + timedelta(minutes=5),
                )
            outliers: list[tuple[int, Literal["full", "propertyless"], dict[str, str]]] = [
                (-3650, "full", {}),
                (-3600, "propertyless", {"$group_0": "account-a"}),
                (3650, "full", {"$group_1": "wrong-index"}),
            ]
            for days, mode, properties in outliers:
                create_event(
                    event_uuid=uuid4(),
                    event="example_action",
                    team=self.team,
                    distinct_id="identified",
                    person_mode=mode,
                    properties=properties,
                    timestamp=start + timedelta(days=days),
                )
            snapshot = timezone.now() + timedelta(minutes=1)
            with patch.object(self.service, "query", wraps=self.service.query) as query:
                plan = self.service.plan(self.team, 0, snapshot)
            planning_windows = [call.args[1] for call in query.call_args_list if "minOrNull(timestamp)" in call.args[0]]
            assert len(planning_windows) == 2
            for window in planning_windows:
                assert timedelta(0) < window["end"] - window["start"] <= timedelta(days=90)
                assert window["snapshot_end"] == snapshot
            assert plan.historical_start == start + timedelta(minutes=5)
            assert plan.historical_end == snapshot
            assert plan.estimated_events == 3
            assert plan.windows == 2
            absent_account = self.service.get_history_bounds(self.team.id, 0, snapshot, ("absent-account",))
            assert absent_account.start is None
            assert absent_account.end == snapshot
            self.process_batch(state)
            first = self.service.query(
                "SELECT group_type_index, group_key, distinct_id, min(first_seen), max(last_seen) FROM person_group_membership WHERE team_id = %(team_id)s GROUP BY group_type_index, group_key, distinct_id",
                {"team_id": self.team.id},
                team_id=self.team.id,
            )
            assert len(first) == 1
            assert first[0][:3] == (0, "account-a", "identified")
            state.next_window_start = start
            state.next_window_end = end
            state.current_group_key = "account-a"
            self.service.save_progress(state)
            self.process_batch(state)
            assert (
                self.service.query(
                    "SELECT group_type_index, group_key, distinct_id, min(first_seen), max(last_seen) FROM person_group_membership WHERE team_id = %(team_id)s GROUP BY group_type_index, group_key, distinct_id",
                    {"team_id": self.team.id},
                    team_id=self.team.id,
                )
                == first
            )
            create_event(
                event_uuid=uuid4(),
                event="example_action",
                team=self.team,
                distinct_id="identified",
                person_mode="full",
                properties={"$group_0": "account-a"},
                timestamp=start + timedelta(minutes=10),
            )
            state.catch_up_end = timezone.now() + timedelta(minutes=1)
            state.next_window_start = timezone.now() - timedelta(minutes=1)
            self.service.save_progress(state)
            self.process_batch(state)
            caught_up = self.service.query(
                "SELECT group_key, distinct_id, min(first_seen), max(last_seen) FROM person_group_membership WHERE team_id = %(team_id)s GROUP BY group_key, distinct_id",
                {"team_id": self.team.id},
                team_id=self.team.id,
            )
            assert len(caught_up) == 1
            assert caught_up[0][:2] == ("account-a", "identified")
            assert caught_up[0][2] == first[0][3]
            assert caught_up[0][3] == cast(datetime, first[0][4]) + timedelta(minutes=5)

    @parameterized.expand([(False,), (True,)])
    def test_history_pages_distinct_ids_without_skipping_a_window(self, native_json: bool) -> None:
        end = timezone.now() + timedelta(minutes=1)
        start = end - timedelta(hours=1)
        state = self.create_state(
            historical_start=start, historical_end=end, next_window_start=start, next_window_end=end
        )
        with (
            patch(f"{MODULE}.use_new_events_schema", return_value=native_json),
            patch(f"{MODULE}.BATCH_SIZE", 2),
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_json),
            events_only_in_active_schema(),
        ):
            for key in ("person-a", "person-b", "person-c"):
                create_person(team=self.team, distinct_ids=[key], is_identified=True)
                create_event(
                    event_uuid=uuid4(),
                    event="example_action",
                    team=self.team,
                    distinct_id=key,
                    person_mode="full",
                    properties={"$group_0": "account-a"},
                    timestamp=start + timedelta(minutes=5),
                )
            assert self.process_batch(state).rows == 2
            assert state.last_distinct_id == "person-b"
            assert state.next_window_end == end
            assert state.windows_completed == 0
            with patch(f"{MODULE}.get_persons_mapped_by_distinct_id", side_effect=RuntimeError("Unavailable")):
                with pytest.raises(RuntimeError, match="Unavailable"):
                    self.process_batch(state)
            assert state.last_distinct_id == "person-b"
            assert self.process_batch(state).rows == 1
        assert state.windows_completed == 1
        assert state.accounts_completed == 1
        assert state.rows_written == 3
        assert self.service.query(
            "SELECT distinct_id FROM person_group_membership WHERE team_id = %(team_id)s GROUP BY distinct_id ORDER BY distinct_id",
            {"team_id": self.team.id},
        ) == [("person-a",), ("person-b",), ("person-c",)]

    @parameterized.expand([(False,), (True,)])
    def test_initial_snapshot_includes_future_timestamped_events(self, native_json: bool) -> None:
        now = timezone.now()
        snapshot_end = now + timedelta(minutes=10)
        future = now + timedelta(hours=12)
        create_person(team=self.team, distinct_ids=["identified"], is_identified=True)
        with (
            patch(f"{MODULE}.use_new_events_schema", return_value=native_json),
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_json),
            events_only_in_active_schema(),
        ):
            create_event(
                event_uuid=uuid4(),
                event="example_action",
                team=self.team,
                distinct_id="identified",
                person_mode="full",
                properties={"$group_0": "account-a"},
                timestamp=future,
            )
            plan = self.service.plan(self.team, 0, snapshot_end)
            assert plan.estimated_events == 1
            with patch(f"{MODULE}.timezone.now", return_value=snapshot_end):
                result = self.service.process_batch(MembershipTeam(team_id=self.team.id))
            assert result.rows == 1
            assert result.cursor is not None
            assert result.cursor.snapshot_end == snapshot_end
            assert result.cursor.historical_end is not None
            assert future < result.cursor.historical_end <= future + timedelta(days=1)
            assert result.cursor.accounts_completed == 1
            assert self.service.query(
                "SELECT min(first_seen), max(last_seen) FROM person_group_membership WHERE team_id = %(team_id)s",
                {"team_id": self.team.id},
            ) == [(future, future)]
            with (
                patch.object(self.service, "dictionary_visible", return_value=True),
                patch(f"{MODULE}.timezone.now", return_value=snapshot_end + timedelta(minutes=1)),
            ):
                caught_up = self.service.process_batch(MembershipTeam(team_id=self.team.id, cursor=result.cursor))
            assert caught_up.cursor is not None
            assert caught_up.cursor.next_window_start == snapshot_end - timedelta(minutes=5)

    def test_initial_snapshot_includes_null_insertion_timestamps(self) -> None:
        end = timezone.now() - timedelta(hours=1)
        start = end - timedelta(days=1)
        create_person(team=self.team, distinct_ids=["identified"], is_identified=True)
        with (
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False),
        ):
            self.service.query(
                """INSERT INTO sharded_events
                    (uuid, event, team_id, distinct_id, timestamp, properties, person_mode, inserted_at) VALUES""",
                [
                    (
                        uuid4(),
                        "example_action",
                        self.team.id,
                        "identified",
                        start,
                        '{"$group_0":"account-a"}',
                        "full",
                        None,
                    ),
                    (
                        uuid4(),
                        "example_action",
                        self.team.id,
                        "identified",
                        start,
                        '{"$group_0":"late-account"}',
                        "full",
                        end + timedelta(minutes=1),
                    ),
                ],
            )
            plan = self.service.plan(self.team, 0, end)
            assert plan.estimated_events == 1
            assert plan.historical_start == start
            state = self.create_state(
                historical_start=start, historical_end=end, current_group_key="", snapshot_end=end
            )
            assert self.process_batch(state).rows == 1
            assert state.accounts_completed == 1
        assert self.service.query(
            "SELECT group_key, min(first_seen), max(last_seen) FROM person_group_membership "
            "WHERE team_id = %(team_id)s GROUP BY group_key",
            {"team_id": self.team.id},
        ) == [("account-a", start, start)]

    @parameterized.expand([(False,), (True,)])
    def test_history_visits_each_account_through_empty_windows(self, native_json: bool) -> None:
        end = timezone.now()
        start = end - timedelta(days=270)
        state = self.create_state(
            historical_start=start,
            historical_end=end,
            next_window_start=start,
            next_window_end=None,
            current_group_key="",
        )
        create_person(team=self.team, distinct_ids=["identified"], is_identified=True)
        raw_create_group_ch(self.team.id, 1, "wrong-index", {}, start)
        other_team = Team.objects.create(organization=self.organization)
        raw_create_group_ch(other_team.id, 0, "wrong-team", {}, start)
        with (
            patch(f"{MODULE}.use_new_events_schema", return_value=native_json),
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_json),
            events_only_in_active_schema(),
            patch(f"{MODULE}.PAGE_SIZE", 1),
        ):
            for key, timestamp in (
                ("account-a", start + timedelta(hours=1)),
                ("account-a", end - timedelta(hours=1)),
                ("account-b", end - timedelta(days=100)),
            ):
                create_event(
                    event_uuid=uuid4(),
                    event="example_action",
                    team=self.team,
                    distinct_id="identified",
                    person_mode="full",
                    properties={"$group_0": key},
                    timestamp=timestamp,
                )
            state.snapshot_end = timezone.now() + timedelta(minutes=1)
            assert self.process_batch(state).status == "backfilling"
            assert state.discovery_window_end == end - timedelta(days=90)
            assert state.accounts_completed == 0
            with patch.object(self.service, "query", side_effect=RuntimeError("Unavailable")):
                with pytest.raises(RuntimeError, match="Unavailable"):
                    self.process_batch(state)
            assert state.discovery_window_end == end - timedelta(days=90)
            for _ in range(20):
                assert self.process_batch(state).status == "backfilling"
                if state.accounts_completed == 2:
                    break
            assert state.accounts_completed == 2
            assert state.windows_completed == 6
            assert state.current_group_key == ""
            assert state.last_group_key == "account-b"
            assert self.service.query(
                "SELECT group_key, distinct_id, min(first_seen), max(last_seen) FROM person_group_membership WHERE team_id = %(team_id)s GROUP BY group_key, distinct_id ORDER BY group_key",
                {"team_id": self.team.id},
                team_id=self.team.id,
            ) == [
                ("account-a", "identified", start + timedelta(hours=1), end - timedelta(hours=1)),
                ("account-b", "identified", end - timedelta(days=100), end - timedelta(days=100)),
            ]

    @parameterized.expand([(False,), (True,)])
    def test_selected_accounts_do_not_mark_team_ready(self, dry_run: bool) -> None:
        state = self.create_state(account_keys=("account-a",), dry_run=dry_run)
        state.next_window_start = END
        state.catch_up_end = END
        with patch.object(self.service, "dictionary_visible", return_value=True):
            assert self.process_batch(state).status == "ready"
        assert get_membership_readiness(self.team) == "backfilling"

    @parameterized.expand([(False,), (True,)])
    def test_selected_catch_up_excludes_other_accounts(self, native_json: bool) -> None:
        start = timezone.now() - timedelta(hours=1)
        end = timezone.now() + timedelta(minutes=1)
        state = self.create_state(
            account_keys=("account-a",),
            catch_up_end=end,
            next_window_start=start,
        )
        create_person(team=self.team, distinct_ids=["identified"], is_identified=True)
        with (
            patch(f"{MODULE}.use_new_events_schema", return_value=native_json),
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=native_json),
            events_only_in_active_schema(),
        ):
            for key in ("account-a", "account-b"):
                create_event(
                    event_uuid=uuid4(),
                    event="example_action",
                    team=self.team,
                    distinct_id="identified",
                    person_mode="full",
                    properties={"$group_0": key},
                )
            assert self.process_batch(state).rows == 1
        assert self.service.query(
            "SELECT group_key FROM person_group_membership WHERE team_id = %(team_id)s GROUP BY group_key",
            {"team_id": self.team.id},
            team_id=self.team.id,
        ) == [("account-a",)]

    def test_dry_run_reads_history_without_membership_or_readiness_writes(self) -> None:
        state = self.create_state(dry_run=True, account_keys=("account-a",))
        with (
            patch.object(self.service, "query", return_value=[("person-a", "account-a", START, START)]) as query,
            patch(f"{MODULE}.use_new_events_schema", return_value=False),
        ):
            result = self.process_batch(state)
        assert result.rows == 0
        assert state.rows_found == 1
        assert state.windows_completed == 1
        assert query.call_count == 1
        assert get_membership_readiness(self.team) == "backfilling"
