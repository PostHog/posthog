import sys
import importlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_storage

from products.data_catalog.backend.facade.api import soft_delete_metric, upsert_metric
from products.data_quality.backend.facade.api import set_schedule
from products.data_quality.backend.logic import contracts
from products.data_quality.backend.logic.flags import (
    is_data_quality_checks_enabled,
    is_data_quality_checks_enabled_for_team_id,
)
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckSchedule

NOW = datetime(2026, 1, 1, 12, 7, tzinfo=UTC)
FLAG = "products.data_quality.backend.logic.schedules.get_data_quality_checks_flag_for_team_id"


class TestScheduleMath(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, NOW, 0, datetime(2026, 1, 1, 13, tzinfo=UTC)),
            ("one_missed", datetime(2026, 1, 1, 11, tzinfo=UTC), NOW, 0, datetime(2026, 1, 1, 13, tzinfo=UTC)),
            ("three_missed", datetime(2026, 1, 1, 9, tzinfo=UTC), NOW, 0, datetime(2026, 1, 1, 13, tzinfo=UTC)),
            (
                "boundary",
                datetime(2026, 1, 1, 11, tzinfo=UTC),
                datetime(2026, 1, 1, 12, tzinfo=UTC),
                0,
                datetime(2026, 1, 1, 13, tzinfo=UTC),
            ),
            ("offset", datetime(2026, 1, 1, 11, 15, tzinfo=UTC), NOW, 15, datetime(2026, 1, 1, 12, 15, tzinfo=UTC)),
            (
                "unsnapped_previous_keeps_a_whole_interval",
                datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
                datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
                15,
                datetime(2026, 1, 1, 13, 15, tzinfo=UTC),
            ),
            (
                "unsnapped_first_run_is_not_pushed_out",
                None,
                datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
                15,
                datetime(2026, 1, 1, 12, 15, tzinfo=UTC),
            ),
        ]
    )
    def test_next_run_skips_missed_slots_and_snaps_to_grid(
        self, _name: str, previous: datetime | None, now: datetime, offset: int, expected: datetime
    ) -> None:
        schedules = importlib.import_module("products.data_quality.backend.logic.schedules")
        assert schedules.next_run_after(previous, timedelta(hours=1), now, timedelta(minutes=offset)) == expected

    def test_schedule_import_has_no_temporal_dependency(self) -> None:
        prefix = "products.data_quality.backend.temporal"
        before = {name for name in sys.modules if name.startswith(prefix)}
        schedules = importlib.import_module("products.data_quality.backend.logic.schedules")
        assert schedules.DueSchedule is contracts.DueSchedule
        assert {name for name in sys.modules if name.startswith(prefix)} == before


class TestSchedules(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.schedules = importlib.import_module("products.data_quality.backend.logic.schedules")
        self.metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="revenue",
            description="Revenue",
            definition={"kind": "HogQLQuery", "query": "SELECT 1"},
        )

    def _schedule(self) -> DataQualityCheckSchedule:
        return self.schedules.get_or_create_schedule(self.team.id, "metric", self.metric.id, now=NOW)

    def _check(self) -> DataQualityCheck:
        return DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type="metric",
            metric_id=self.metric.id,
            subject_name="revenue",
            check_type="custom_sql",
            config={"query": "SELECT * FROM {metric} WHERE 1 = 0"},
            fingerprint="a" * 64,
        )

    def test_first_run_is_immediate_and_schedule_is_unique(self) -> None:
        schedule = self._schedule()
        assert schedule.next_run_at == NOW
        assert schedule.interval == timedelta(days=1)
        assert self._schedule().id == schedule.id
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(schedule).objects.for_team(self.team.id).create(
                team=self.team, subject_type="metric", subject_uuid=self.metric.id, next_run_at=NOW
            )

    @parameterized.expand([(True,), (False,)])
    def test_read_leaves_occurrence_due_until_acknowledged(self, enabled: bool) -> None:
        schedule = self._schedule()
        self._check()
        with patch(FLAG, return_value=enabled):
            batch = self.schedules.claim_due_schedule_batch(NOW, 50)
            assert len(batch.schedules) == int(enabled)
            assert len(batch.skipped_schedules) == int(not enabled)
            schedule.refresh_from_db()
            assert schedule.next_run_at == NOW
            assert schedule.last_run_at is None
            due = (batch.schedules or batch.skipped_schedules)[0]
            assert self.schedules.acknowledge_schedule(due, NOW)
            assert not self.schedules.acknowledge_schedule(due, NOW)
            assert not self.schedules.claim_due_schedules(NOW, 50)
        schedule.refresh_from_db()
        assert schedule.next_run_at > NOW
        assert schedule.last_run_at is None

    def test_stale_acknowledgement_preserves_cadence_edit(self) -> None:
        self._schedule()
        self._check()
        with patch(FLAG, return_value=True):
            due = self.schedules.claim_due_schedules(NOW, 1)[0]
        updated = self.schedules.set_schedule(self.team.id, "metric", self.metric.id, interval="1hour", now=NOW)
        assert not self.schedules.acknowledge_schedule(due, NOW)
        updated.refresh_from_db()
        assert updated.next_run_at > NOW
        assert updated.interval == timedelta(hours=1)

    @parameterized.expand([(None,), (False,)])
    @override_settings(DEBUG=False, E2E_TESTING=False)
    def test_unknown_flag_result_is_not_an_intentionally_disabled_occurrence(self, flag_result: bool | None) -> None:
        schedule = self._schedule()
        self._check()
        with patch("posthoganalytics.feature_enabled", return_value=flag_result):
            batch = self.schedules.claim_due_schedule_batch(NOW, 1)
            assert not is_data_quality_checks_enabled(self.team)
            assert not is_data_quality_checks_enabled_for_team_id(self.team.id)
        assert not batch.schedules
        assert len(batch.skipped_schedules) == int(flag_result is False)
        assert batch.next_cursor is not None
        assert batch.next_cursor.schedule_id == schedule.id
        schedule.refresh_from_db()
        assert schedule.next_run_at == NOW
        assert schedule.last_run_at is None

    def test_flag_failure_keeps_occurrence_due_and_cursor_advances(self) -> None:
        schedule = self._schedule()
        self._check()
        with patch(FLAG, side_effect=RuntimeError("flag unavailable")):
            batch = self.schedules.claim_due_schedule_batch(NOW, 1)
        assert not batch.schedules
        assert not batch.skipped_schedules
        assert batch.next_cursor is not None
        assert batch.next_cursor.schedule_id == schedule.id
        assert not self.schedules.claim_due_schedule_batch(NOW, 1, after=batch.next_cursor).claimed_count
        schedule.refresh_from_db()
        assert schedule.next_run_at == NOW
        assert schedule.last_run_at is None

    @parameterized.expand([("none",), ("disabled",), ("deleted",), ("metric_deleted",)])
    def test_claim_excludes_subject_without_enabled_live_check(self, state: str) -> None:
        schedule = self._schedule()
        if state != "none":
            check = self._check()
            DataQualityCheck.objects.for_team(self.team.id).filter(id=check.id).update(
                enabled=state != "disabled", deleted=state == "deleted"
            )
        if state == "metric_deleted":
            soft_delete_metric(self.metric)
        with patch(FLAG, return_value=True):
            assert self.schedules.claim_due_schedules(NOW, 50) == []
        schedule.refresh_from_db()
        assert schedule.next_run_at == NOW

    def test_schedule_update_recomputes_interval_without_restarting_on_toggle(self) -> None:
        schedule = self._schedule()
        type(schedule).objects.for_team(self.team.id).filter(id=schedule.id).update(id=UUID(int=0))
        schedule.id = UUID(int=0)
        schedule.last_run_at = datetime(2026, 1, 1, 11, tzinfo=UTC)
        schedule.save()
        updated = self.schedules.set_schedule(
            self.team.id, "metric", self.metric.id, interval="1hour", enabled=False, now=NOW
        )
        assert updated.next_run_at == datetime(2026, 1, 1, 13, tzinfo=UTC)
        assert not updated.enabled
        updated = self.schedules.set_schedule(self.team.id, "metric", self.metric.id, enabled=True, now=NOW)
        assert updated.next_run_at == datetime(2026, 1, 1, 13, tzinfo=UTC)
        with self.assertRaises(ValueError):
            self.schedules.set_schedule(self.team.id, "metric", self.metric.id, interval="5minute", now=NOW)

    def test_claim_limit_future_disabled_and_team_flag_after_transaction(self) -> None:
        schedules = []
        for index in range(5):
            metric = upsert_metric(
                team=self.team,
                user=self.user,
                name=f"metric_{index}",
                description="Metric",
                definition={"kind": "HogQLQuery", "query": "SELECT 1"},
            )
            schedule = self.schedules.get_or_create_schedule(self.team.id, "metric", metric.id, now=NOW)
            DataQualityCheck.objects.for_team(self.team.id).create(
                team=self.team,
                subject_type="metric",
                metric_id=metric.id,
                subject_name=metric.name,
                check_type="custom_sql",
                fingerprint="a" * 64,
            )
            schedules.append(schedule)
        schedules[3].next_run_at = NOW + timedelta(days=1)
        schedules[3].save(update_fields=["next_run_at"])
        schedules[4].enabled = False
        schedules[4].save(update_fields=["enabled"])
        transaction_depth = len(connection.atomic_blocks)

        def enabled(team_id: int) -> bool:
            assert team_id == self.team.id
            assert len(connection.atomic_blocks) == transaction_depth
            return True

        with patch(FLAG, side_effect=enabled) as flag:
            first = self.schedules.claim_due_schedules(NOW, 2)
            assert len(first) == 2
            assert flag.call_count == 1
            remaining = self.schedules.claim_due_schedule_batch(NOW, 50, after=first[-1]).schedules
            assert len(remaining) == 1
            assert flag.call_count == 2
        assert {item.schedule_id for item in first + remaining} == {schedule.id for schedule in schedules[:3]}

    def test_schedule_is_absent_before_first_check_and_labels_are_validated(self) -> None:
        assert self.schedules.get_schedule(self.team.id, "metric", self.metric.id) is None
        with self.assertRaises(self.schedules.DataQualityCheckSchedule.DoesNotExist):
            self.schedules.set_schedule(self.team.id, "metric", self.metric.id, enabled=False, now=NOW)
        assert self.schedules.interval_from_label("7day") == timedelta(days=7)
        assert self.schedules.label_from_interval(timedelta(hours=6)) == "6hour"
        with self.assertRaises(ValueError):
            self.schedules.label_from_interval(timedelta(minutes=5))

    def test_claim_excludes_non_metric_subjects(self) -> None:
        schedule = self._schedule()
        check = self._check()
        DataQualityCheck.objects.for_team(self.team.id).filter(id=check.id).update(
            subject_type="table", metric_id=None, table_id=self.metric.id
        )
        DataQualityCheckSchedule.objects.for_team(self.team.id).filter(id=schedule.id).update(subject_type="table")
        with patch(FLAG, return_value=True):
            assert self.schedules.claim_due_schedules(NOW, 50) == []

    def test_claim_batch_counts_rows_excluded_by_flag(self) -> None:
        self._schedule()
        self._check()
        flags: dict[int, bool] = {}
        with patch(FLAG, return_value=False) as flag:
            batch = self.schedules.claim_due_schedule_batch(NOW, 1, enabled_teams=flags)
        assert batch.claimed_count == 1
        assert batch.schedules == []
        assert flags == {self.team.id: False}
        assert flag.call_count == 1

    def test_schedule_activity_names_the_metric_it_belongs_to(self) -> None:
        other = upsert_metric(
            team=self.team,
            user=self.user,
            name="signups",
            description="Signups",
            definition={"kind": "HogQLQuery", "query": "SELECT 1"},
        )
        for metric_id in (self.metric.id, other.id):
            self.schedules.get_or_create_schedule(self.team.id, "metric", metric_id, now=NOW)
        activity_storage.set_user(self.user)
        try:
            set_schedule(self.team.id, "metric", self.metric.id, interval="1hour")
            set_schedule(self.team.id, "metric", other.id, interval="1hour")
        finally:
            activity_storage.clear_user()
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="DataQualityCheckSchedule", activity="updated")
        assert {log.detail["name"] for log in logs} == {
            "metric check schedule on revenue",
            "metric check schedule on signups",
        }

    def test_schedule_config_audits_actor_and_ignores_dispatch_bookkeeping(self) -> None:
        schedule = self.schedules.get_or_create_schedule(
            self.team.id, "metric", self.metric.id, now=NOW, created_by_id=self.user.id
        )
        assert schedule.created_by_id == self.user.id
        activity_storage.set_user(self.user)
        try:
            set_schedule(self.team.id, "metric", self.metric.id, interval="1hour", enabled=False)
            logs = ActivityLog.objects.filter(
                team_id=self.team.id, scope="DataQualityCheckSchedule", activity="updated"
            )
            changed = logs.get()
            assert changed.user_id == self.user.id
            assert changed.detail is not None
            assert {change["field"] for change in changed.detail["changes"]} == {"interval", "enabled"}
            set_schedule(self.team.id, "metric", self.metric.id, interval="1hour", enabled=False)
            schedule.refresh_from_db()
            schedule.next_run_at = NOW
            schedule.last_run_at = NOW
            schedule.save(update_fields=["next_run_at", "last_run_at", "updated_at"])
            assert logs.count() == 1
        finally:
            activity_storage.clear_user()
