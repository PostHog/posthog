from posthog.models.cohort import Cohort
from posthog.test.base import BaseTest


class TestCohort(BaseTest):
    def test_cohort_filters_priority_over_groups(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "actions",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        }
                    ],
                }
            },
        )

        self.assertEqual(cohort.properties.values[0].key, "$pageview")
