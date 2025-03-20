from ee.hogai.summarizers.cohorts import CohortPropertyDescriber
from posthog.models import Action
from posthog.models.property.property import Property
from posthog.test.base import BaseTest

"""
1. cohort tests
"""


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
            == "people who completed the event `$pageview` where the event property `$browser` matches exactly `Chrome` in the last 30 days"
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
                    operator="icontains",
                ),
            ],
            explicit_datetime="-1dStart",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == "people who completed the event `$pageview` where the person property `name` matches exactly `John` AND the person property `surname` contains `Mc` yesterday"
        )

    def test_behavioral_cohort_performed_event_with_negation(self):
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event",
            negation=True,
            event_type="events",
            explicit_datetime="2025-03-10",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == "people who did not complete the event `$pageview` on 2025-03-10"
        )

    def test_behavioral_cohort_performed_action(self):
        action = Action.objects.create(team=self.team, name="Completed onboarding")

        prop = Property(
            key=str(action.id),
            type="behavioral",
            value="performed_event",
            negation=False,
            event_type="actions",
            explicit_datetime="2025-03-10",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == f"people who completed the action `Completed onboarding` with ID `{action.id}` on 2025-03-10"
        )

    def test_behavioral_cohort_performed_unexisting_action_with_negation(self):
        prop = Property(
            key="0",
            type="behavioral",
            value="performed_event",
            negation=True,
            event_type="actions",
            explicit_datetime="2025-03-10",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == f"people who did not complete an unknown action with ID `0` on 2025-03-10"
        )

    def test_behavioral_cohort_performed_event_multiple_times(self):
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event_multiple",
            negation=False,
            event_type="events",
            explicit_datetime="-7d",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summarize()
            == "people who did not complete the event `$pageview` on 2025-03-10"
        )
