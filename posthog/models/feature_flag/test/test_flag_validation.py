from datetime import datetime

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.cohort import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.feature_flag.flag_validation import _exclude_realtime_backfilled_cohort_properties
from posthog.models.property.property import Property

BEHAVIORAL_FILTERS = {
    "properties": {
        "type": "OR",
        "values": [
            {
                "type": "behavioral",
                "key": "$pageview",
                "value": "performed_event",
                "event_type": "events",
                "time_value": 30,
                "time_interval": "day",
            }
        ],
    }
}


class TestExcludeRealtimeBackfilledCohortProperties(APIBaseTest):
    def _make_cohort_property(self, cohort_id: int) -> Property:
        return Property(type="cohort", key="id", value=cohort_id)

    def _make_person_property(self) -> Property:
        return Property(type="person", key="email", value="test@posthog.com")

    @parameterized.expand(
        [
            # (name, cohort_kwargs, allow_realtime_backfilled, expect_cohort_filtered)
            (
                "disabled_flag_keeps_all",
                {"cohort_type": CohortType.REALTIME, "last_backfill_person_properties_at": datetime.now()},
                False,
                False,
            ),
            (
                "enabled_realtime_backfilled_filtered",
                {"cohort_type": CohortType.REALTIME, "last_backfill_person_properties_at": datetime.now()},
                True,
                True,
            ),
            (
                "enabled_realtime_not_backfilled_kept",
                {"cohort_type": CohortType.REALTIME, "last_backfill_person_properties_at": None},
                True,
                False,
            ),
            (
                "enabled_non_realtime_kept",
                {},
                True,
                False,
            ),
        ]
    )
    def test_cohort_filtering(self, _name, cohort_kwargs, allow_realtime_backfilled, expect_cohort_filtered):
        cohort = Cohort.objects.create(
            team=self.team,
            name="test-cohort",
            filters=BEHAVIORAL_FILTERS,
            **cohort_kwargs,
        )
        person_prop = self._make_person_property()
        props = [self._make_cohort_property(cohort.pk), person_prop]

        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=allow_realtime_backfilled
        )

        if expect_cohort_filtered:
            assert result == [person_prop]
        else:
            assert result == props

    def test_keeps_non_cohort_properties_untouched(self):
        person_prop = self._make_person_property()
        result = _exclude_realtime_backfilled_cohort_properties(
            [person_prop], self.team.project.id, allow_realtime_backfilled=True
        )
        assert result == [person_prop]

    def test_handles_nonexistent_cohort_gracefully(self):
        props = [self._make_cohort_property(99999)]
        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=True
        )
        assert result == props

    def test_handles_deleted_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="deleted-cohort",
            filters=BEHAVIORAL_FILTERS,
            cohort_type=CohortType.REALTIME,
            last_backfill_person_properties_at=datetime.now(),
            deleted=True,
        )
        props = [self._make_cohort_property(cohort.pk)]

        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=True
        )
        # Deleted cohorts aren't found by the query (deleted=False), so they're kept
        assert result == props
