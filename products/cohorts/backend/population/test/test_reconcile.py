from io import StringIO
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, flush_persons_and_events

from django.core.management import call_command

from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import CohortPopulationSource, CohortPopulationStatus
from products.cohorts.backend.models.util import count_cohort_members, insert_static_cohort
from products.cohorts.backend.population import (
    operation as lifecycle,
    reconcile,
    runner,
)


class TestStaticCohortMembershipReconciliation(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cohort = Cohort.objects.create(team=self.team, name="half written", is_static=True)

    def _write_to_clickhouse_only(self, count: int) -> list:
        people = [create_person(team=self.team, distinct_ids=[f"drifted-{index}"]) for index in range(count)]
        flush_persons_and_events()
        insert_static_cohort([person.uuid for person in people], self.cohort.pk, team_id=self.team.pk)
        return people

    def test_the_audit_reports_the_resolvable_members_postgres_is_missing(self) -> None:
        self._write_to_clickhouse_only(3)

        audit = reconcile.audit_cohort(self.cohort)

        assert audit.clickhouse_members == 3
        assert audit.resolvable_members == 3
        assert audit.postgres_members == 0
        assert audit.missing_from_postgres == 3
        assert audit.needs_repair is True

    def test_a_person_clickhouse_kept_but_nobody_can_resolve_is_not_counted_as_drift(self) -> None:
        self._write_to_clickhouse_only(2)
        insert_static_cohort([UUID("00000000-0000-0000-0000-0000000000ff")], self.cohort.pk, team_id=self.team.pk)

        audit = reconcile.audit_cohort(self.cohort)

        assert audit.clickhouse_members == 3
        assert audit.resolvable_members == 2
        assert audit.unresolvable_members == 1
        assert audit.missing_from_postgres == 2

    def test_a_consistent_cohort_needs_no_repair(self) -> None:
        people = self._write_to_clickhouse_only(2)
        self.cohort.insert_users_list_by_uuid([str(person.uuid) for person in people], team_id=self.team.pk)

        assert reconcile.audit_cohort(self.cohort).needs_repair is False

    def test_a_repair_writes_the_missing_members_and_leaves_the_import_incomplete(self) -> None:
        self._write_to_clickhouse_only(3)
        assert self.cohort.last_import_total_count is None

        operation = reconcile.start_reconciliation(self.cohort)
        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert operation.source == CohortPopulationSource.RECONCILE
        assert count_cohort_members(team_id=self.team.pk, cohort_id=self.cohort.pk, consistency="strong") == 3
        assert self.cohort.count == 3
        assert self.cohort.last_import_total_count is None
        assert reconcile.audit_cohort(self.cohort).needs_repair is False

    def test_a_repair_will_not_start_underneath_a_run_that_is_already_going(self) -> None:
        self._write_to_clickhouse_only(2)
        reconcile.start_reconciliation(self.cohort)

        with pytest.raises(lifecycle.CohortPopulationConflict):
            reconcile.start_reconciliation(self.cohort)

    def test_the_audit_command_is_read_only_and_prints_a_resume_cursor(self) -> None:
        self._write_to_clickhouse_only(2)
        output = StringIO()

        call_command("reconcile_static_cohort_membership", "audit", "--team-id", str(self.team.pk), stdout=output)

        printed = output.getvalue()
        assert f"next-cursor: {self.cohort.pk}" in printed
        assert "1 of 1 cohorts need repair." in printed
        assert lifecycle.latest_operation_for(self.cohort.pk) is None

    def test_the_repair_command_starts_nothing_until_live_run(self) -> None:
        self._write_to_clickhouse_only(2)
        output = StringIO()

        call_command("reconcile_static_cohort_membership", "repair", "--cohort-id", str(self.cohort.pk), stdout=output)

        assert "Dry run" in output.getvalue()
        assert lifecycle.latest_operation_for(self.cohort.pk) is None

        call_command(
            "reconcile_static_cohort_membership",
            "repair",
            "--cohort-id",
            str(self.cohort.pk),
            "--live-run",
            stdout=StringIO(),
        )

        assert count_cohort_members(team_id=self.team.pk, cohort_id=self.cohort.pk, consistency="strong") == 2
