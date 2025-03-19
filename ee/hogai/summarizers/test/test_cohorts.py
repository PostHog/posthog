from ee.hogai.summarizers.cohorts import CohortPropertyDescriber
from posthog.models.property.property import Property
from posthog.test.base import BaseTest


class TestPropertySummarizer(BaseTest):
    def test_behavioral_cohort_performed_event(self):
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event",
            negation=False,
            event_type="events",
            event_filters=[
                Property(
                    key="$browser",
                    type="event",
                    value=["Chrome"],
                    operator="exact",
                )
            ],
            explicit_datetime="-30d",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == "people who performed an event `$pageview` where the event property `$browser` matches exactly `Chrome` in the last 30 days"
        )

    def test_behavioral_cohort_performed_event_with_multiple_filters(self):
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event",
            negation=False,
            event_type="events",
            event_filters=[
                Property(
                    key="name",
                    type="person",
                    value="John",
                    operator="exact",
                ),
                Property(
                    key="surname",
                    type="person",
                    value="Mc",
                    operator="contains",
                ),
            ],
            explicit_datetime="-1dStart",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == "people who performed an event `$pageview` where the person property `$name` matches exactly `John` AND the person property `$surname` contains `Mc` yesterday"
        )
