import uuid
from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import OperationalError
from django.utils import timezone

from celery.exceptions import Retry, SoftTimeLimitExceeded
from parameterized import parameterized
from prometheus_client import REGISTRY
from redis.exceptions import RedisError

from posthog.models.instance_setting import override_instance_config
from posthog.redis import get_client
from posthog.tasks.calculate_cohort import (
    dispatch_static_cohort_reconciliations,
    reconcile_static_cohort_membership,
    reset_stuck_cohorts,
)
from posthog.test.persons import create_person

from products.cohorts.backend import static_reconciliation
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import (
    StaticCohortReadBackIncomplete,
    count_cohort_members,
    delete_cohort_member,
    insert_cohort_people_into_pg,
    insert_static_cohort,
)
from products.cohorts.backend.static_reconciliation import (
    StaticCohortToReconcile,
    reconcile_static_cohort,
    run_reconciliation_pass,
)


class TestStaticCohortReconciliation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.now = timezone.now()

    def _static_cohort(
        self, *, clickhouse_members: int = 0, person_uuids: tuple[Any, ...] = (), **fields: Any
    ) -> Cohort:
        fields = {"last_calculation": self.now - timedelta(days=7), "count": 0, **fields}
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True, **fields)
        uuids = [*person_uuids, *(uuid.uuid4() for _ in range(clickhouse_members))]
        with time_machine.travel(self.now - timedelta(days=7), tick=False):
            insert_static_cohort(uuids, cohort.pk, team_id=self.team.pk)
        return cohort

    def _dispatched(self) -> list[StaticCohortToReconcile]:
        dispatched: list[StaticCohortToReconcile] = []
        run_reconciliation_pass(now=self.now, dispatch=dispatched.append)
        return dispatched

    def _dispatched_ids(self) -> list[int]:
        return [cohort.cohort_id for cohort in self._dispatched()]

    def _forget_attempts(self, *cohorts: Cohort) -> None:
        cache.delete_many([static_reconciliation._hold_cache_key(cohort.pk) for cohort in cohorts])

    @parameterized.expand([(True,), (False,)])
    def test_sweep_copies_clickhouse_members_to_postgres_unless_switched_off(self, enabled: bool) -> None:
        people = [create_person(team=self.team, distinct_ids=[f"member-{i}"]) for i in range(2)]
        cohort = self._static_cohort(person_uuids=tuple(person.uuid for person in people))

        with override_instance_config("STATIC_COHORT_RECONCILIATION_ENABLED", enabled):
            dispatch_static_cohort_reconciliations()

        expected = 2 if enabled else 0
        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), expected)
        self.assertEqual(cohort.count, expected)
        self.assertFalse(cohort.is_calculating)

    @parameterized.expand(
        [
            ("empty_postgres", 0, 3, {}, True),
            ("unknown_count", None, 3, {}, True),
            ("missing_more_than_one_percent", 197, 200, {}, True),
            ("missing_one_percent", 198, 200, {}, False),
            ("postgres_complete", 3, 3, {}, False),
            ("too_large", 0, 300, {}, False),
            ("still_calculating", 0, 3, {"is_calculating": True}, False),
            ("calculated_within_settle_delay", 0, 3, {"last_calculation_ago": timedelta(minutes=10)}, False),
            ("never_calculated_settled", 0, 3, {"last_calculation": None, "created_at_ago": timedelta(hours=2)}, True),
            ("never_calculated_new", 0, 3, {"last_calculation": None, "created_at_ago": timedelta(minutes=10)}, False),
            ("errored_within_settle_delay", 0, 3, {"last_error_at_ago": timedelta(minutes=10)}, False),
            ("errored_long_ago", 0, 3, {"last_error_at_ago": timedelta(days=2)}, True),
            ("deleted", 0, 3, {"deleted": True}, False),
            ("last_population_failed", 0, 3, {"errors_calculating": 1}, False),
        ]
    )
    @patch.object(static_reconciliation, "RECONCILE_MAX_MEMBERS", 250)
    def test_dispatches_only_settled_cohorts_whose_postgres_count_lags(
        self,
        _name: str,
        stored_count: int | None,
        clickhouse_members: int,
        fields: dict[str, Any],
        expected_dispatched: bool,
    ) -> None:
        fields = dict(fields)
        for field in ("last_calculation", "last_error_at", "created_at"):
            if f"{field}_ago" in fields:
                fields[field] = self.now - fields.pop(f"{field}_ago")
        created_at = fields.pop("created_at", None)
        cohort = self._static_cohort(clickhouse_members=clickhouse_members, count=stored_count, **fields)
        if created_at is not None:
            Cohort.objects.filter(pk=cohort.pk).update(created_at=created_at)

        expected = StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk)
        self.assertEqual(self._dispatched(), [expected] if expected_dispatched else [])

    @patch.object(static_reconciliation, "RECONCILE_PAGE_SIZE", 2)
    @patch.object(static_reconciliation, "RECONCILE_MAX_COHORTS_PER_RUN", 1)
    def test_walks_from_newest_to_oldest_and_starts_again_from_the_newest(self) -> None:
        oldest, middle, newest = (self._static_cohort(clickhouse_members=1) for _ in range(3))

        passes = [self._dispatched_ids() for _ in range(3)]
        self._forget_attempts(oldest, middle, newest)
        passes.append(self._dispatched_ids())

        self.assertEqual(passes, [[newest.pk], [middle.pk], [oldest.pk], [newest.pk]])

    @patch.object(static_reconciliation, "RECONCILE_PAGE_SIZE", 2)
    def test_cursor_moves_past_a_full_page_with_nothing_to_repair(self) -> None:
        lagging = self._static_cohort(clickhouse_members=1)
        for _ in range(2):
            self._static_cohort(clickhouse_members=1, count=1)

        self.assertEqual([self._dispatched_ids(), self._dispatched_ids()], [[], [lagging.pk]])

    @patch.object(static_reconciliation, "RECONCILE_MAX_COHORTS_PER_RUN", 2)
    @patch.object(static_reconciliation, "RECONCILE_MAX_RECENT_PER_RUN", 1)
    def test_recent_cohorts_leave_part_of_the_budget_to_the_backlog(self) -> None:
        old = self._static_cohort(clickhouse_members=1)
        recent = [
            self._static_cohort(clickhouse_members=1, last_calculation=self.now - timedelta(hours=3)) for _ in range(2)
        ]

        self.assertEqual(self._dispatched_ids(), [recent[1].pk, old.pk])

    def test_does_not_dispatch_a_recent_cohort_again_within_the_retry_window(self) -> None:
        cohort = self._static_cohort(clickhouse_members=3, last_calculation=self.now - timedelta(hours=3))

        self.assertEqual([self._dispatched_ids(), self._dispatched_ids()], [[cohort.pk], []])

    @patch.object(static_reconciliation, "RECONCILE_PAGE_SIZE", 1)
    def test_a_held_recent_cohort_does_not_hide_an_older_one(self) -> None:
        older, newer = (
            self._static_cohort(clickhouse_members=1, last_calculation=self.now - timedelta(hours=hours))
            for hours in (4, 3)
        )
        static_reconciliation._hold(newer.pk, timedelta(hours=1))

        self.assertEqual(self._dispatched_ids(), [older.pk])

    def test_a_failed_dispatch_is_retried_on_the_next_pass(self) -> None:
        cohort = self._static_cohort(clickhouse_members=3)

        def fail(_cohort: StaticCohortToReconcile) -> None:
            raise ConnectionError("broker down")

        run_reconciliation_pass(now=self.now, dispatch=fail)

        self.assertEqual(self._dispatched_ids(), [cohort.pk])

    def test_parks_a_cohort_whose_gap_a_repair_cannot_close(self) -> None:
        person = create_person(team=self.team, distinct_ids=["kept"])
        # The second ClickHouse member has no person, like a person deleted after the population.
        cohort = self._static_cohort(clickhouse_members=1, person_uuids=(person.uuid,))

        passes = []
        for _ in range(3):
            dispatched = self._dispatched()
            passes.append([c.cohort_id for c in dispatched])
            for target in dispatched:
                reconcile_static_cohort(target)
            self._forget_attempts(cohort)

        insert_static_cohort([uuid.uuid4()], cohort.pk, team_id=self.team.pk)
        passes.append(self._dispatched_ids())

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 1)
        self.assertEqual(passes, [[cohort.pk], [cohort.pk], [], [cohort.pk]])

    def test_a_repair_that_finds_the_cohort_busy_copies_nothing_and_the_next_pass_retries(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,))
        [target] = self._dispatched()

        Cohort.objects.filter(pk=cohort.pk).update(is_calculating=True)
        reconcile_static_cohort(target)
        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 0)

        Cohort.objects.filter(pk=cohort.pk).update(is_calculating=False)
        self.assertEqual(self._dispatched(), [target])

    @parameterized.expand(
        [
            ("finished", {"last_calculation_now": True}),
            ("failed", {"errors_calculating": 1, "last_error_at_now": True}),
        ]
    )
    def test_repair_keeps_the_count_of_an_import_that_ended_during_the_copy(
        self, _name: str, import_end: dict[str, Any]
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,))
        update = {
            key.removesuffix("_now"): timezone.now() if key.endswith("_now") else value
            for key, value in import_end.items()
        }

        def copy_while_an_import_finishes(*args: Any, **kwargs: Any) -> None:
            insert_cohort_people_into_pg(*args, **kwargs)
            Cohort.objects.filter(pk=cohort.pk).update(count=5, **update)

        with patch.object(
            static_reconciliation, "insert_cohort_people_into_pg", side_effect=copy_while_an_import_finishes
        ) as copy:
            reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 5)
        self.assertEqual(copy.call_args.kwargs["min_rows"], 1)

    def test_stuck_cohort_sweep_leaves_a_repair_in_progress_alone(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,), query={"kind": "HogQLQuery", "query": "select 1"})

        def copy_while_the_sweep_runs(*args: Any, **kwargs: Any) -> None:
            reset_stuck_cohorts()
            insert_cohort_people_into_pg(*args, **kwargs)

        with (
            patch.object(static_reconciliation, "insert_cohort_people_into_pg", side_effect=copy_while_the_sweep_runs),
            patch("posthog.tasks.calculate_cohort.insert_cohort_from_query"),
        ):
            reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        cohort.refresh_from_db()
        self.assertEqual((cohort.errors_calculating, cohort.count), (0, 1))

    def test_repair_fixes_a_stale_count_when_postgres_has_every_member(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,))
        cohort.insert_users_list_by_uuid_into_pg_only([str(person.uuid)], team_id=self.team.pk)
        Cohort.objects.filter(pk=cohort.pk).update(count=0, last_calculation=self.now - timedelta(days=7))

        reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 1)

    def test_parks_a_complete_cohort_with_duplicate_clickhouse_rows(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid, person.uuid))
        cohort.insert_users_list_by_uuid_into_pg_only([str(person.uuid)], team_id=self.team.pk)
        Cohort.objects.filter(pk=cohort.pk).update(count=1, last_calculation=self.now - timedelta(days=7))

        [target] = self._dispatched()
        reconcile_static_cohort(target)
        self._forget_attempts(cohort)

        self.assertEqual(self._dispatched(), [])

    @parameterized.expand([("copy_succeeds", False), ("copy_fails_after_writing", True)])
    def test_a_member_removed_during_a_repair_stays_removed(self, _name: str, copy_fails: bool) -> None:
        removed, kept = (create_person(team=self.team, distinct_ids=[f"member-{i}"]) for i in range(2))
        cohort = self._static_cohort(person_uuids=(removed.uuid, kept.uuid))
        self.addCleanup(get_client().delete, static_reconciliation._removed_members_key(cohort.pk))

        def remove_then_copy(*args: Any, **kwargs: Any) -> None:
            # The ClickHouse delete has not applied yet, so the copy still reads the removed member.
            with patch("products.cohorts.backend.models.util.remove_person_from_static_cohort"):
                cohort.remove_user_by_uuid(str(removed.uuid), team_id=self.team.pk)
            insert_cohort_people_into_pg(*args, **kwargs)
            if copy_fails:
                raise StaticCohortReadBackIncomplete("read 1 of 2 rows")

        target = StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk)
        with patch.object(static_reconciliation, "insert_cohort_people_into_pg", side_effect=remove_then_copy):
            if copy_fails:
                with self.assertRaises(StaticCohortReadBackIncomplete):
                    reconcile_static_cohort(target)
            else:
                reconcile_static_cohort(target)

        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 1)

    @parameterized.expand([("explicit_addition",), ("query_population",)])
    def test_a_member_removed_and_added_again_stays_added(self, how: str) -> None:
        person, other = (create_person(team=self.team, distinct_ids=[f"member-{i}"]) for i in range(2))
        cohort = self._static_cohort(person_uuids=(person.uuid, other.uuid))
        self.addCleanup(get_client().delete, static_reconciliation._removed_members_key(cohort.pk))
        # The ClickHouse delete has not applied yet, so the old row is still there.
        with patch("products.cohorts.backend.models.util.remove_person_from_static_cohort"):
            cohort.remove_user_by_uuid(str(person.uuid), team_id=self.team.pk)
        if how == "explicit_addition":
            cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.pk, save_state=False)
        else:
            written_since = (self.now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
            # A mark is kept for a row written in the same second as the removal.
            with time_machine.travel(timezone.now() + timedelta(seconds=5), tick=False):
                insert_static_cohort([person.uuid], cohort.pk, team_id=self.team.pk)
            insert_cohort_people_into_pg(cohort, team_id=self.team.pk, min_rows=1, written_since=written_since)
        Cohort.objects.filter(pk=cohort.pk).update(count=0)

        reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 2)

    @parameterized.expand(
        [("by_an_earlier_population", timedelta(days=7)), ("by_this_population", timedelta(minutes=5))]
    )
    def test_a_population_keeps_out_a_member_whose_row_was_written_before_the_removal(
        self, _name: str, written_ago: timedelta
    ) -> None:
        removed, added = (create_person(team=self.team, distinct_ids=[f"member-{i}"]) for i in range(2))
        cohort = self._static_cohort()
        self.addCleanup(get_client().delete, static_reconciliation._removed_members_key(cohort.pk))
        written_since = (self.now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        with time_machine.travel(self.now - written_ago, tick=False):
            insert_static_cohort([removed.uuid], cohort.pk, team_id=self.team.pk)
        # The ClickHouse delete has not applied yet when the population copies its rows to Postgres.
        with patch("products.cohorts.backend.models.util.remove_person_from_static_cohort"):
            cohort.remove_user_by_uuid(str(removed.uuid), team_id=self.team.pk)
        with time_machine.travel(timezone.now() + timedelta(seconds=5), tick=False):
            insert_static_cohort([added.uuid], cohort.pk, team_id=self.team.pk)
        insert_cohort_people_into_pg(cohort, team_id=self.team.pk, min_rows=1, written_since=written_since)
        Cohort.objects.filter(pk=cohort.pk).update(count=0)

        reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 1)

    def test_a_member_added_again_while_a_repair_deletes_removed_members_stays_added(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,))
        self.addCleanup(get_client().delete, static_reconciliation._removed_members_key(cohort.pk))
        cohort.insert_users_list_by_uuid_into_pg_only([str(person.uuid)], team_id=self.team.pk)
        static_reconciliation.record_static_cohort_member_removal(
            cohort_id=cohort.pk, person_id=person.id, person_uuid=str(person.uuid)
        )

        def add_again_then_delete(*args: Any) -> bool:
            # The addition lands after the repair read the marks but before its delete.
            cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.pk, save_state=False)
            return delete_cohort_member(*args)

        # The cleanup after the copy, so no later copy puts the member back.
        with patch.object(static_reconciliation, "delete_cohort_member", side_effect=add_again_then_delete):
            static_reconciliation._delete_recently_removed_members(cohort)

        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 1)

    @parameterized.expand([("recent", timedelta(hours=1), 1), ("expired", timedelta(days=8), 2)])
    def test_a_retry_that_finds_the_cohort_complete_still_deletes_removed_members(
        self, _name: str, removed_ago: timedelta, expected_members: int
    ) -> None:
        removed, kept = (create_person(team=self.team, distinct_ids=[f"member-{i}"]) for i in range(2))
        cohort = self._static_cohort(person_uuids=(removed.uuid, kept.uuid))
        self.addCleanup(get_client().delete, static_reconciliation._removed_members_key(cohort.pk))
        # A copy brought the removed member back and the cleanup after it failed.
        cohort.insert_users_list_by_uuid_into_pg_only([str(removed.uuid), str(kept.uuid)], team_id=self.team.pk)
        Cohort.objects.filter(pk=cohort.pk).update(count=2, last_calculation=self.now - timedelta(days=7))
        with time_machine.travel(self.now - removed_ago, tick=False):
            static_reconciliation.record_static_cohort_member_removal(
                cohort_id=cohort.pk, person_id=removed.id, person_uuid=str(removed.uuid)
            )
        # A later removal of someone else renews the key, so only the entry's own age can expire it.
        with time_machine.travel(self.now - timedelta(days=2), tick=False):
            static_reconciliation.record_static_cohort_member_removal(
                cohort_id=cohort.pk, person_id=999_999_999, person_uuid=str(uuid.uuid4())
            )

        reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), expected_members)
        self.assertEqual(
            get_client().hexists(static_reconciliation._removed_members_key(cohort.pk), str(removed.uuid)),
            removed_ago < static_reconciliation.RECONCILE_REMOVAL_TTL,
        )

    def test_a_failed_recount_does_not_park_the_cohort(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,))
        target = StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk)

        with (
            patch.object(static_reconciliation, "count_cohort_members", side_effect=[0, ConnectionError("down")]),
            self.assertRaises(ConnectionError),
        ):
            reconcile_static_cohort(target)

        self.assertEqual(self._dispatched(), [target])

    @parameterized.expand(
        [
            ("transient", OperationalError("connection reset"), True),
            ("redis", RedisError("connection reset"), True),
            ("read_back_incomplete", StaticCohortReadBackIncomplete("read 1 of 2 rows"), False),
            ("soft_time_limit", SoftTimeLimitExceeded(), False),
        ]
    )
    @patch("posthog.tasks.calculate_cohort.reconcile_static_cohort")
    def test_task_retries_only_transient_errors(
        self, _name: str, error: Exception, retries: bool, repair: MagicMock
    ) -> None:
        repair.side_effect = error
        task = reconcile_static_cohort_membership
        failed_before = REGISTRY.get_sample_value("cohort_static_reconcile_total", {"outcome": "failed"}) or 0
        task.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            if retries:
                with self.assertRaises(Retry):
                    task.run(team_id=self.team.pk, cohort_id=1)
            else:
                task.run(team_id=self.team.pk, cohort_id=1)
        finally:
            task.pop_request()

        failed_after = REGISTRY.get_sample_value("cohort_static_reconcile_total", {"outcome": "failed"}) or 0
        self.assertEqual(failed_after - failed_before, 0 if retries else 1)

    @patch("posthog.tasks.calculate_cohort.reconcile_static_cohort")
    def test_a_queued_repair_does_nothing_once_switched_off(self, repair: MagicMock) -> None:
        with override_instance_config("STATIC_COHORT_RECONCILIATION_ENABLED", False):
            reconcile_static_cohort_membership.run(team_id=self.team.pk, cohort_id=1)

        repair.assert_not_called()

    @parameterized.expand(
        [("redis_error", ConnectionError("redis down"), 1), ("soft_time_limit", SoftTimeLimitExceeded(), 0)]
    )
    def test_a_failure_while_clearing_a_removal_stops_the_addition_only_at_the_time_limit(
        self, _name: str, error: Exception, expected_members: int
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True)

        with patch.object(static_reconciliation, "_user_path_redis", side_effect=error):
            if isinstance(error, SoftTimeLimitExceeded):
                with self.assertRaises(SoftTimeLimitExceeded):
                    cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.pk)
            else:
                cohort.insert_users_list_by_uuid([str(person.uuid)], team_id=self.team.pk)

        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), expected_members)
