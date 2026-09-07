from datetime import timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.models.utils import uuid7

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    CohortPopulationOperation,
    CohortPopulationPhase,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.models.util import CohortErrorCode
from products.cohorts.backend.population import operation as lifecycle
from products.cohorts.backend.population.progress import PopulationProgress

MANIFEST = {"schema": 1, "prefix": "cohort_population/team-1/op", "chunks": 3, "total": 2500, "id_type": "distinct_id"}


class TestCohortPopulationOperationLifecycle(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cohort = Cohort.objects.create(team=self.team, name="uploaded people", is_static=True)

    def test_failed_operations_keep_the_cohort_reserved(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="w")
        assert claimed is not None
        lifecycle.fail_permanently(claimed, error_code=CohortErrorCode.UNKNOWN)
        assert lifecycle.claim(operation.pk, worker="duplicate") is None
        with pytest.raises(lifecycle.CohortPopulationConflict):
            self._admit()

    def test_an_expired_owner_cannot_checkpoint_or_finalize_without_a_replacement(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="w")
        assert claimed is not None
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert not lifecycle.checkpoint(claimed, progress=PopulationProgress(chunk_index=1))
        assert not lifecycle.complete(claimed, count=99)
        self.cohort.refresh_from_db()
        assert self.cohort.is_calculating
        assert self.cohort.count != 99

    def _admit(self, *, source=CohortPopulationSource.LIST, manifest=MANIFEST) -> CohortPopulationOperation:
        return lifecycle.admit(
            operation_id=uuid7(),
            cohort=self.cohort,
            team_id=self.team.pk,
            source=source,
            input_manifest=manifest,
        )

    def test_admission_marks_the_cohort_calculating_and_starts_in_the_source_phase(self) -> None:
        operation = self._admit(source=CohortPopulationSource.QUERY, manifest=None)

        self.cohort.refresh_from_db()
        assert self.cohort.is_calculating is True
        assert operation.phase == CohortPopulationPhase.MATERIALIZING_SOURCE
        assert operation.status == CohortPopulationStatus.PENDING

    def test_a_list_operation_starts_straight_at_writing_membership(self) -> None:
        assert self._admit().phase == CohortPopulationPhase.WRITING_MEMBERSHIP

    def test_a_second_unresolved_operation_for_the_same_cohort_is_refused(self) -> None:
        first = self._admit()

        with pytest.raises(lifecycle.CohortPopulationConflict) as conflict:
            self._admit()

        assert conflict.value.operation.pk == first.pk

    def test_a_new_operation_is_admitted_once_the_previous_one_resolved(self) -> None:
        first = self._admit()
        lifecycle.claim(first.pk, worker="w1")
        first.refresh_from_db()
        lifecycle.complete(first)

        second = self._admit()

        assert second.pk != first.pk

    def test_a_duplicate_delivery_cannot_claim_a_live_attempt(self) -> None:
        operation = self._admit()
        first_claim = lifecycle.claim(operation.pk, worker="worker-a")

        assert first_claim is not None
        assert lifecycle.claim(operation.pk, worker="worker-b") is None

    @override_settings(COHORT_POPULATION_LEASE_SECONDS=60)
    def test_a_replacement_worker_claims_the_operation_once_the_lease_expires(self) -> None:
        operation = self._admit()
        with freeze_time("2026-09-07T10:00:00Z"):
            lost = lifecycle.claim(operation.pk, worker="worker-a")
        assert lost is not None

        with freeze_time("2026-09-07T10:02:00Z"):
            replacement = lifecycle.claim(operation.pk, worker="worker-b")

        assert replacement is not None
        assert replacement.claim_token != lost.claim_token

    def test_a_write_from_the_replaced_attempt_changes_nothing(self) -> None:
        operation = self._admit()
        lost = lifecycle.claim(operation.pk, worker="worker-a")
        assert lost is not None
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            lease_expires_at=timezone.now() - timedelta(minutes=1)
        )
        replacement = lifecycle.claim(operation.pk, worker="worker-b")
        assert replacement is not None
        lifecycle.checkpoint(replacement, progress=PopulationProgress(chunk_index=2))

        accepted = lifecycle.checkpoint(lost, progress=PopulationProgress(chunk_index=99))

        assert accepted is False
        operation.refresh_from_db()
        assert PopulationProgress.from_json(operation.progress).chunk_index == 2

    def test_a_second_terminal_transition_from_the_same_attempt_is_refused(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="worker-a")
        assert claimed is not None
        assert lifecycle.complete(claimed) is True

        assert lifecycle.abandon(claimed) is False
        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED

    def test_a_scheduled_retry_is_not_claimable_before_its_backoff_elapses(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="worker-a")
        assert claimed is not None
        lifecycle.schedule_retry(claimed, error_code=CohortErrorCode.CAPACITY)

        assert lifecycle.claim(operation.pk, worker="worker-b") is None

    def test_a_scheduled_retry_becomes_claimable_once_its_backoff_elapses(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="worker-a")
        assert claimed is not None
        lifecycle.schedule_retry(claimed, error_code=CohortErrorCode.CAPACITY)
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            next_attempt_at=timezone.now() - timedelta(seconds=1)
        )

        assert lifecycle.claim(operation.pk, worker="worker-b") is not None

    def test_backoff_grows_with_each_attempt_and_stops_at_the_cap(self) -> None:
        with patch("products.cohorts.backend.population.operation.random.uniform", return_value=0.0):
            assert lifecycle._backoff_seconds(1) == pytest.approx(60.0)
            assert lifecycle._backoff_seconds(2) == pytest.approx(120.0)
            assert lifecycle._backoff_seconds(20) == pytest.approx(lifecycle.RETRY_MAX_BACKOFF_SECONDS)

    def test_the_operation_fails_once_the_retry_budget_is_spent_and_keeps_its_input(self) -> None:
        operation = self._admit()
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(max_attempts=2)

        for _ in range(3):
            CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(next_attempt_at=None)
            claimed = lifecycle.claim(operation.pk, worker="worker-a")
            assert claimed is not None
            lifecycle.schedule_retry(claimed, error_code=CohortErrorCode.CAPACITY)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.FAILED
        assert operation.attempts == 3
        assert operation.error_code == CohortErrorCode.CAPACITY
        assert operation.input_manifest == MANIFEST
        assert operation.input_deleted_at is None

    def test_a_permanent_failure_ends_the_run_without_spending_the_budget(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="worker-a")
        assert claimed is not None

        lifecycle.fail_permanently(claimed, error_code=CohortErrorCode.INPUT_UNAVAILABLE)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.FAILED
        assert operation.attempts == 1
        assert operation.next_attempt_at is None

    def test_a_retry_resumes_saved_progress_with_a_fresh_budget(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="worker-a")
        assert claimed is not None
        lifecycle.checkpoint(claimed, progress=PopulationProgress(chunk_index=2, matched=1800, unmatched=200))
        lifecycle.fail_permanently(claimed, error_code=CohortErrorCode.CAPACITY)
        operation.refresh_from_db()

        lifecycle.reopen_for_retry(operation, requested_by_id=None)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.PENDING
        assert operation.attempts == 0
        assert operation.error_code == ""
        assert PopulationProgress.from_json(operation.progress).chunk_index == 2
        assert self.cohort.is_calculating is True

    @override_settings(
        COHORT_POPULATION_COMPLETED_INPUT_RETENTION_HOURS=24, COHORT_POPULATION_FAILED_INPUT_RETENTION_DAYS=30
    )
    def test_a_completed_run_keeps_its_input_for_a_day_and_a_failed_run_for_a_month(self) -> None:
        with freeze_time("2026-09-07T10:00:00Z") as frozen:
            completed = self._admit()
            claimed = lifecycle.claim(completed.pk, worker="w")
            assert claimed is not None
            lifecycle.complete(claimed)
            completed.refresh_from_db()
            assert completed.input_expires_at == timezone.now() + timedelta(hours=24)

            frozen.tick(timedelta(seconds=1))
            failed = self._admit()
            assert failed.input_expires_at == timezone.now() + timedelta(days=30)

    def test_reaping_input_marks_it_gone_so_a_retry_stops_offering_to_resume(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="w")
        assert claimed is not None
        lifecycle.fail_permanently(claimed, error_code=CohortErrorCode.UNKNOWN)
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            input_expires_at=timezone.now() - timedelta(seconds=1)
        )
        with patch("products.cohorts.backend.population.operation.delete_input") as delete:
            lifecycle.reap_input(operation)

        delete.assert_called_once_with(MANIFEST)
        operation.refresh_from_db()
        assert operation.input_deleted_at is not None
        assert lifecycle.input_looks_available(operation) is False

    def test_an_abandon_request_does_not_have_to_sit_through_a_retry_backoff(self) -> None:
        operation = self._admit()
        claimed = lifecycle.claim(operation.pk, worker="worker-a")
        assert claimed is not None
        lifecycle.schedule_retry(claimed, error_code=CohortErrorCode.CAPACITY)
        assert lifecycle.claim(operation.pk, worker="worker-b") is None

        operation.refresh_from_db()
        lifecycle.request_abandon(operation)

        assert lifecycle.claim(operation.pk, worker="worker-b") is not None

    def test_a_live_attempt_still_holds_its_lease_against_an_abandon_request(self) -> None:
        operation = self._admit()
        assert lifecycle.claim(operation.pk, worker="worker-a") is not None
        operation.refresh_from_db()
        lifecycle.request_abandon(operation)

        assert lifecycle.claim(operation.pk, worker="worker-b") is None
