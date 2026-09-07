from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.models.utils import uuid7

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    CohortPopulationOperation,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.population import (
    dispatch,
    operation as lifecycle,
)
from products.cohorts.backend.population.admission import admit_query_or_filters_population

MANIFEST = {"schema": 1, "prefix": "cohort_population/team-1/op", "chunks": 1, "total": 1, "id_type": "person_id"}


class TestCohortPopulationDispatch(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dispatched: list[str] = []
        patcher = patch.object(dispatch, "dispatch_operation", side_effect=lambda pk: self.dispatched.append(str(pk)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _operation(self, name: str, **overrides) -> CohortPopulationOperation:
        cohort = Cohort.objects.create(team=self.team, name=name, is_static=True)
        operation = lifecycle.admit(
            operation_id=uuid7(),
            cohort=cohort,
            team_id=self.team.pk,
            source=CohortPopulationSource.LIST,
            input_manifest=MANIFEST,
        )
        if overrides:
            CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(**overrides)
            operation.refresh_from_db()
        return operation

    def test_a_publish_that_never_landed_is_dispatched_again(self) -> None:
        operation = self._operation("never published")

        result = dispatch.dispatch_ready_operations()

        assert result.missed_dispatch == 1
        assert self.dispatched == [str(operation.pk)]
        operation.refresh_from_db()
        assert operation.dispatched_at is not None

    def test_an_operation_already_dispatched_is_left_alone_until_the_grace_passes(self) -> None:
        operation = self._operation("just published", dispatched_at=timezone.now())

        assert dispatch.dispatch_ready_operations().dispatched == 0

        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            dispatched_at=timezone.now() - dispatch.MISSED_DISPATCH_GRACE - timedelta(seconds=1)
        )
        assert dispatch.dispatch_ready_operations().missed_dispatch == 1

    def test_a_run_published_at_admission_is_not_republished_before_the_grace(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="from query", is_static=True)
        admit_query_or_filters_population(cohort=cohort, team_id=self.team.pk, source=CohortPopulationSource.QUERY)

        assert dispatch.dispatch_ready_operations().dispatched == 0

    def test_a_retry_is_dispatched_once_due_and_not_while_waiting_or_already_published(self) -> None:
        due = self._operation(
            "due",
            status=CohortPopulationStatus.RETRY_SCHEDULED,
            next_attempt_at=timezone.now() - timedelta(seconds=1),
        )
        self._operation(
            "waiting",
            status=CohortPopulationStatus.RETRY_SCHEDULED,
            next_attempt_at=timezone.now() + timedelta(minutes=10),
        )
        self._operation(
            "due but published within the grace",
            status=CohortPopulationStatus.RETRY_SCHEDULED,
            next_attempt_at=timezone.now() - timedelta(seconds=1),
            dispatched_at=timezone.now(),
        )

        result = dispatch.dispatch_ready_operations()

        assert result.retry_due == 1
        assert self.dispatched == [str(due.pk)]

    def test_an_operation_whose_worker_died_is_dispatched_once_its_lease_expires(self) -> None:
        lost = self._operation(
            "lost worker",
            status=CohortPopulationStatus.RUNNING,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        self._operation(
            "healthy",
            status=CohortPopulationStatus.RUNNING,
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
        self._operation(
            "lost worker published within the grace",
            status=CohortPopulationStatus.RUNNING,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            dispatched_at=timezone.now(),
        )

        result = dispatch.dispatch_ready_operations()

        assert result.lost_worker == 1
        assert self.dispatched == [str(lost.pk)]

    def test_a_resolved_operation_is_never_redispatched(self) -> None:
        self._operation("done", status=CohortPopulationStatus.COMPLETED)
        self._operation("failed", status=CohortPopulationStatus.FAILED)

        assert dispatch.dispatch_ready_operations().dispatched == 0

    @override_settings(COHORT_POPULATION_MAX_DISPATCHES_PER_PASS=2)
    def test_one_pass_dispatches_no_more_than_its_ceiling(self) -> None:
        for index in range(4):
            self._operation(f"backlog-{index}")

        assert dispatch.dispatch_ready_operations().dispatched == 2

    def test_input_past_its_retention_is_deleted_and_recorded_as_gone(self) -> None:
        expired = self._operation(
            "expired",
            status=CohortPopulationStatus.COMPLETED,
            input_expires_at=timezone.now() - timedelta(seconds=1),
        )

        with patch("products.cohorts.backend.population.operation.delete_input") as delete:
            result = dispatch.dispatch_ready_operations()

        assert result.reaped_inputs == 1
        delete.assert_called_once_with(MANIFEST)
        expired.refresh_from_db()
        assert expired.input_deleted_at is not None

    def test_input_of_an_unresolved_operation_is_never_reaped(self) -> None:
        self._operation("still running", input_expires_at=timezone.now() - timedelta(seconds=1))

        with patch("products.cohorts.backend.population.operation.delete_input") as delete:
            result = dispatch.dispatch_ready_operations()

        assert result.reaped_inputs == 0
        delete.assert_not_called()
