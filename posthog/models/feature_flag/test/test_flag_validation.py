from datetime import datetime

from posthog.test.base import APIBaseTest

from posthog.models.cohort import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.feature_flag.flag_validation import _exclude_realtime_backfilled_cohort_properties
from posthog.models.property.property import Property


class TestExcludeRealtimeBackfilledCohortProperties(APIBaseTest):
    def _make_cohort_property(self, cohort_id: int) -> Property:
        return Property(type="cohort", key="id", value=cohort_id)

    def _make_person_property(self) -> Property:
        return Property(type="person", key="email", value="test@posthog.com")

    def test_returns_unchanged_when_disabled(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="realtime-backfilled",
            filters={
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
            },
            cohort_type=CohortType.REALTIME,
            last_backfill_person_properties_at=datetime.now(),
        )
        props = [self._make_cohort_property(cohort.pk), self._make_person_property()]

        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=False
        )
        assert result == props

    def test_filters_out_flag_compatible_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="realtime-backfilled",
            filters={
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
            },
            cohort_type=CohortType.REALTIME,
            last_backfill_person_properties_at=datetime.now(),
        )
        person_prop = self._make_person_property()
        props = [self._make_cohort_property(cohort.pk), person_prop]

        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=True
        )
        assert result == [person_prop]

    def test_keeps_non_backfilled_realtime_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="realtime-not-backfilled",
            filters={
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
            },
            cohort_type=CohortType.REALTIME,
            last_backfill_person_properties_at=None,
        )
        props = [self._make_cohort_property(cohort.pk), self._make_person_property()]

        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=True
        )
        assert result == props

    def test_keeps_non_realtime_behavioral_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="dynamic-behavioral",
            filters={
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
            },
        )
        props = [self._make_cohort_property(cohort.pk)]

        result = _exclude_realtime_backfilled_cohort_properties(
            props, self.team.project.id, allow_realtime_backfilled=True
        )
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
            filters={
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
            },
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
