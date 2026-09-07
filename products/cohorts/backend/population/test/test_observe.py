from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.utils import uuid7

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    CohortPopulationOperation,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.population import (
    observe,
    operation as lifecycle,
)


class TestCohortPopulationObservation(BaseTest):
    def _operation(self, name: str, source=CohortPopulationSource.LIST, **overrides):
        cohort = Cohort.objects.create(team=self.team, name=name, is_static=True)
        operation = lifecycle.admit(operation_id=uuid7(), cohort=cohort, team_id=self.team.pk, source=source)
        if overrides:
            CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(**overrides)
            operation.refresh_from_db()
        return operation

    def test_every_status_and_source_is_published_even_when_empty(self) -> None:
        result = observe._observe()

        assert result.active_operations[CohortPopulationStatus.PENDING, CohortPopulationSource.QUERY] == 0
        assert result.recent_operations[CohortPopulationStatus.FAILED, CohortPopulationSource.LIST] == 0
        assert result.incomplete_imports[CohortPopulationSource.FEATURE_FLAG] == 0

    def test_unresolved_operations_are_counted_by_status_and_source(self) -> None:
        self._operation("pending list")
        self._operation("pending query", source=CohortPopulationSource.QUERY)
        self._operation("retrying", status=CohortPopulationStatus.RETRY_SCHEDULED)

        result = observe._observe()

        assert result.active_operations[CohortPopulationStatus.PENDING, CohortPopulationSource.LIST] == 1
        assert result.active_operations[CohortPopulationStatus.PENDING, CohortPopulationSource.QUERY] == 1
        assert result.active_operations[CohortPopulationStatus.RETRY_SCHEDULED, CohortPopulationSource.LIST] == 1

    def test_the_oldest_unresolved_operation_sets_the_stall_age(self) -> None:
        self._operation("recent")
        old = self._operation("old", created_at=timezone.now() - timedelta(hours=3))
        CohortPopulationOperation.objects.unscoped().filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(hours=3)
        )

        age = observe._observe().oldest_active_age_seconds[CohortPopulationStatus.PENDING, CohortPopulationSource.LIST]

        assert age > timedelta(hours=2).total_seconds()

    def test_an_incomplete_import_is_counted_apart_from_the_stores_agreeing(self) -> None:
        self._operation("failed", status=CohortPopulationStatus.FAILED, finished_at=timezone.now())
        self._operation("abandoned", status=CohortPopulationStatus.ABANDONED, finished_at=timezone.now())
        self._operation("completed", status=CohortPopulationStatus.COMPLETED, finished_at=timezone.now())

        result = observe._observe()

        assert result.incomplete_imports[CohortPopulationSource.LIST] == 2
        assert result.recent_operations[CohortPopulationStatus.COMPLETED, CohortPopulationSource.LIST] == 1

    def test_an_operation_that_finished_before_the_window_is_no_longer_recent(self) -> None:
        self._operation(
            "old failure",
            status=CohortPopulationStatus.FAILED,
            finished_at=timezone.now() - observe.RECENT_WINDOW - timedelta(minutes=1),
        )

        result = observe._observe()

        assert result.recent_operations[CohortPopulationStatus.FAILED, CohortPopulationSource.LIST] == 0
        assert result.incomplete_imports[CohortPopulationSource.LIST] == 0
