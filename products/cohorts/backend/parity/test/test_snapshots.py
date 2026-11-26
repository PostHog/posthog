from posthog.test.base import BaseTest

from django.utils import timezone

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.parity.snapshots import load_realtime_cohorts


class TestLoadRealtimeCohorts(BaseTest):
    def _cohort(self, *, realtime_enabled: bool, is_static: bool = False) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            realtime_enabled_at=timezone.now() if realtime_enabled else None,
            is_static=is_static,
            filters={},
        )

    def test_loads_only_realtime_cohorts_that_are_on_and_not_static(self) -> None:
        on = self._cohort(realtime_enabled=True)
        self._cohort(realtime_enabled=False)
        self._cohort(realtime_enabled=True, is_static=True)

        assert [cohort.pk for cohort in load_realtime_cohorts(self.team.id)] == [on.pk]
