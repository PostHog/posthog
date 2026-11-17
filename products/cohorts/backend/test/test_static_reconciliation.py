import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import OperationalError
from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.tasks.calculate_cohort import (
    reconcile_static_cohort_membership,
    reconcile_static_cohorts,
    reset_stuck_cohorts,
)
from posthog.test.persons import create_person

from products.cohorts.backend import static_reconciliation
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import (
    StaticCohortReadBackIncomplete,
    count_cohort_members,
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
            reconcile_static_cohorts()

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
            ("deleted", 0, 3, {"deleted": True}, False),
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
        if "last_calculation_ago" in fields:
            fields["last_calculation"] = self.now - fields.pop("last_calculation_ago")
        cohort = self._static_cohort(clickhouse_members=clickhouse_members, count=stored_count, **fields)

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

    def test_does_not_dispatch_a_recent_cohort_again_within_the_retry_window(self) -> None:
        cohort = self._static_cohort(clickhouse_members=3, last_calculation=self.now - timedelta(hours=3))

        self.assertEqual([self._dispatched_ids(), self._dispatched_ids()], [[cohort.pk], []])

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

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 1)
        self.assertEqual(passes, [[cohort.pk], [cohort.pk], []])

    def test_repair_leaves_a_cohort_that_another_task_is_calculating(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,), is_calculating=True)

        reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), 0)
        self.assertTrue(cohort.is_calculating)

    def test_stuck_cohort_sweep_leaves_a_repair_in_progress_alone(self) -> None:
        person = create_person(team=self.team, distinct_ids=["member"])
        cohort = self._static_cohort(person_uuids=(person.uuid,), query={"kind": "HogQLQuery", "query": "select 1"})

        def copy_while_the_sweep_runs(*args: Any, **kwargs: Any) -> None:
            reset_stuck_cohorts()
            insert_cohort_people_into_pg(*args, **kwargs)

        with (
            patch.object(static_reconciliation, "insert_cohort_people_into_pg", side_effect=copy_while_the_sweep_runs),
            patch("posthog.tasks.calculate_cohort.insert_cohort_from_query") as population,
        ):
            reconcile_static_cohort(StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk))

        cohort.refresh_from_db()
        population.delay.assert_not_called()
        self.assertEqual((cohort.errors_calculating, cohort.count), (0, 1))

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
            ("read_back_incomplete", StaticCohortReadBackIncomplete("read 1 of 2 rows"), False),
        ]
    )
    @patch("posthog.tasks.calculate_cohort.reconcile_static_cohort")
    def test_task_retries_only_transient_errors(
        self, _name: str, error: Exception, retries: bool, repair: MagicMock
    ) -> None:
        repair.side_effect = error
        task = reconcile_static_cohort_membership
        task.push_request(retries=0, called_directly=False, is_eager=True)
        try:
            if retries:
                with self.assertRaises(Retry):
                    task.run(team_id=self.team.pk, cohort_id=1)
            else:
                task.run(team_id=self.team.pk, cohort_id=1)
        finally:
            task.pop_request()
