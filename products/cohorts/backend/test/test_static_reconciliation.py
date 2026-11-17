import uuid
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.tasks.calculate_cohort import reconcile_static_cohorts
from posthog.test.persons import create_person

from products.cohorts.backend import static_reconciliation
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import count_cohort_members, insert_static_cohort
from products.cohorts.backend.static_reconciliation import StaticCohortToReconcile, select_static_cohorts_to_reconcile


class TestStaticCohortReconciliation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.now = timezone.now()

    def _static_cohort(self, *, clickhouse_members: int, **fields: Any) -> Cohort:
        fields = {"last_calculation": self.now - timedelta(days=7), "count": 0, **fields}
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True, **fields)
        insert_static_cohort([uuid.uuid4() for _ in range(clickhouse_members)], cohort.pk, team_id=self.team.pk)
        return cohort

    def _select(self) -> list[int]:
        return [cohort.cohort_id for cohort in select_static_cohorts_to_reconcile(now=self.now)]

    @parameterized.expand([(True,), (False,)])
    def test_sweep_copies_clickhouse_members_to_postgres_unless_switched_off(self, enabled: bool) -> None:
        people = [create_person(team=self.team, distinct_ids=[f"member-{i}"]) for i in range(2)]
        cohort = Cohort.objects.create(
            team=self.team, name="static", is_static=True, last_calculation=self.now - timedelta(days=7), count=0
        )
        insert_static_cohort([person.uuid for person in people], cohort.pk, team_id=self.team.pk)

        with override_instance_config("STATIC_COHORT_RECONCILIATION_ENABLED", enabled):
            reconcile_static_cohorts()

        expected = 2 if enabled else 0
        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.pk, cohort.pk), expected)
        self.assertEqual(cohort.count, expected)

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
    def test_selects_only_settled_cohorts_whose_postgres_count_lags(
        self,
        _name: str,
        stored_count: int | None,
        clickhouse_members: int,
        fields: dict[str, Any],
        expected_selected: bool,
    ) -> None:
        fields = dict(fields)
        if "last_calculation_ago" in fields:
            fields["last_calculation"] = self.now - fields.pop("last_calculation_ago")
        cohort = self._static_cohort(clickhouse_members=clickhouse_members, count=stored_count, **fields)

        self.assertEqual(
            select_static_cohorts_to_reconcile(now=self.now),
            [StaticCohortToReconcile(team_id=self.team.pk, cohort_id=cohort.pk)] if expected_selected else [],
        )

    @patch.object(static_reconciliation, "RECONCILE_PAGE_SIZE", 2)
    @patch.object(static_reconciliation, "RECONCILE_MAX_COHORTS_PER_RUN", 1)
    def test_walks_from_newest_to_oldest_and_starts_again_from_the_newest(self) -> None:
        oldest, middle, newest = (self._static_cohort(clickhouse_members=1) for _ in range(3))

        passes = [self._select() for _ in range(3)]
        cache.delete_many([static_reconciliation._attempt_cache_key(c.pk) for c in (oldest, middle, newest)])
        passes.append(self._select())

        self.assertEqual(passes, [[newest.pk], [middle.pk], [oldest.pk], [newest.pk]])

    def test_does_not_retry_a_cohort_whose_gap_stays_open(self) -> None:
        cohort = self._static_cohort(clickhouse_members=3, last_calculation=self.now - timedelta(hours=3))

        self.assertEqual([self._select(), self._select()], [[cohort.pk], []])
