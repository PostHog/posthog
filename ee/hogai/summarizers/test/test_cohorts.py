from ee.hogai.summarizers.cohorts import CohortPropertyDescriber
from posthog.models import Action, Cohort
from posthog.models.property.property import Property
from posthog.test.base import BaseTest

"""
1. cohort tests
"""


class TestPropertySummarizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(team=self.team, name="Completed onboarding")
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Visited homepage",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"type": "event", "key": "$title", "operator": "in", "value": "Homepage"}],
                        }
                    ],
                }
            },
        )

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
            CohortPropertyDescriber(self.team, prop).summary
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
            CohortPropertyDescriber(self.team, prop).summary
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
            CohortPropertyDescriber(self.team, prop).summary
            == "people who did not complete the event `$pageview` on 2025-03-10"
        )

    def test_behavioral_cohort_performed_action(self):
        prop = Property(
            key=str(self.action.id),
            type="behavioral",
            value="performed_event",
            negation=False,
            event_type="actions",
            explicit_datetime="2025-03-10",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who completed the action `Completed onboarding` with ID `{self.action.id}` on 2025-03-10"
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
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who did not complete an unknown action with ID `0` on 2025-03-10"
        )

    def test_behavioral_cohort_performed_event_multiple_times(self):
        # Exact
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event_multiple",
            negation=False,
            event_type="events",
            explicit_datetime="-7d",
            operator_value=1,
            operator="exact",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who completed the event `$pageview` exactly 1 time in the last 7 days"
        )
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event_multiple",
            negation=False,
            event_type="events",
            explicit_datetime="-7d",
            operator_value=2,
            operator="exact",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who completed the event `$pageview` exactly 2 times in the last 7 days"
        )

        # GTE
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event_multiple",
            negation=True,
            event_type="events",
            explicit_datetime="-1dStart",
            operator_value=10,
            operator="gte",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who did not complete the event `$pageview` at least 10 times yesterday"
        )

        # LTE
        prop = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event_multiple",
            negation=False,
            event_type="events",
            explicit_datetime="2025-03-10",
            operator_value=10,
            operator="lte",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who completed the event `$pageview` at most 10 times on 2025-03-10"
        )

    def test_behavioral_cohort_performed_action_multiple_times(self):
        action = self.action
        prop = Property(
            key=str(action.id),
            type="behavioral",
            value="performed_event_multiple",
            negation=False,
            event_type="actions",
            explicit_datetime="-7d",
            operator_value=2,
            operator="exact",
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
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who completed the action `Completed onboarding` with ID `{action.id}` where the person property `name` matches exactly `John` AND the person property `surname` contains `Mc` exactly 2 times in the last 7 days"
        )

    def test_behavioral_cohort_performed_event_sequence(self):
        prop = Property(
            type="behavioral",
            value="performed_event_sequence",
            negation=False,
            key="cohort created",
            event_type="events",
            time_value=10,
            time_interval="day",
            seq_event="cohort created",
            seq_event_type="events",
            seq_time_value=1,
            seq_time_interval="day",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who completed a sequence of the event `cohort created` in the last 10 days followed by the event `cohort created` within 1 day of the initial event"
        )

        prop = Property(
            type="behavioral",
            value="performed_event_sequence",
            negation=True,
            key="cohort created",
            event_type="events",
            time_value=1,
            time_interval="year",
            seq_event="cohort created",
            seq_event_type="events",
            seq_time_value=3,
            seq_time_interval="month",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who did not complete a sequence of the event `cohort created` in the last 1 year followed by the event `cohort created` within 3 months of the initial event"
        )

    def test_behavioral_cohort_performed_action_sequence(self):
        action = self.action
        prop = Property(
            type="behavioral",
            value="performed_event_sequence",
            negation=False,
            key=str(action.id),
            event_type="actions",
            time_value=10,
            time_interval="day",
            seq_event=str(action.id),
            seq_event_type="actions",
            seq_time_value=1,
            seq_time_interval="day",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who completed a sequence of the action `Completed onboarding` with ID `{action.id}` in the last 10 days followed by the action `Completed onboarding` with ID `{action.id}` within 1 day of the initial event"
        )

        prop = Property(
            type="behavioral",
            value="performed_event_sequence",
            negation=True,
            key=str(action.id),
            event_type="actions",
            time_value=1,
            time_interval="year",
            seq_event=str(action.id),
            seq_event_type="actions",
            seq_time_value=3,
            seq_time_interval="month",
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who did not complete a sequence of the action `Completed onboarding` with ID `{action.id}` in the last 1 year followed by the action `Completed onboarding` with ID `{action.id}` within 3 months of the initial event"
        )

    def test_person_has_property(self):
        prop = Property(
            key="$browser",
            negation=False,
            operator="exact",
            type="person",
            value=["Chrome"],
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who have the person property `$browser` that matches exactly `Chrome`"
        )

    def test_person_has_not_property(self):
        prop = Property(
            key="$browser",
            negation=True,
            operator="exact",
            type="person",
            value=["Chrome"],
        )
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == "people who do not have the person property `$browser` that matches exactly `Chrome`"
        )

    def test_person_is_in_cohort(self):
        prop = Property(key="id", type="cohort", value=self.cohort.id)
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who are a part of the dynamic cohort `Visited homepage` with ID `{self.cohort.id}` having the following filters (people who have the event property `$title` that is one of the values in `Homepage`)"
        )

    def test_person_is_not_in_cohort(self):
        prop = Property(key="id", type="cohort", negation=True, value=self.cohort.id)
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who are not a part of the dynamic cohort `Visited homepage` with ID `{self.cohort.id}` having the following filters (people who have the event property `$title` that is one of the values in `Homepage`)"
        )

    def test_precalculated_cohort(self):
        prop = Property(key="id", type="precalculated-cohort", value=self.cohort.id)
        assert (
            CohortPropertyDescriber(self.team, prop).summary
            == f"people who are a part of the dynamic cohort `Visited homepage` with ID `{self.cohort.id}` having the following filters (people who have the event property `$title` that is one of the values in `Homepage`)"
        )
