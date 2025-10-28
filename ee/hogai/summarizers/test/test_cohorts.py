from textwrap import dedent

from ee.hogai.summarizers.cohorts import CohortPropertyGroupSummarizer, CohortPropertySummarizer, CohortSummarizer
from posthog.constants import PropertyOperatorType
from posthog.models import Action, Cohort
from posthog.models.property.property import Property, PropertyGroup
from posthog.test.base import BaseTest


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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
            == "people who completed the event `$pageview` exactly once in the last 7 days"
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
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
            CohortPropertySummarizer(self.team, prop).summary
            == "people who do not have the person property `$browser` that matches exactly `Chrome`"
        )

    def test_person_is_in_cohort(self):
        prop = Property(key="id", type="cohort", value=self.cohort.id)
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == f"people who are a part of the dynamic cohort `Visited homepage` with ID `{self.cohort.id}` having the following filters (people who have the event property `$title` that is one of the values in `Homepage`)"
        )

    def test_person_is_not_in_cohort(self):
        prop = Property(key="id", type="cohort", negation=True, value=self.cohort.id)
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == f"people who are not a part of the dynamic cohort `Visited homepage` with ID `{self.cohort.id}` having the following filters (people who have the event property `$title` that is one of the values in `Homepage`)"
        )

    def test_precalculated_cohort(self):
        prop = Property(key="id", type="precalculated-cohort", value=self.cohort.id)
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == f"people who are a part of the dynamic cohort `Visited homepage` with ID `{self.cohort.id}` having the following filters (people who have the event property `$title` that is one of the values in `Homepage`)"
        )

    def test_lifecycle_first_time_event(self):
        prop = Property(
            type="behavioral",
            value="performed_event_first_time",
            key="$pageview",
            event_type="events",
            time_value=30,
            time_interval="day",
            negation=False,
        )
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who performed the event `$pageview` for the first time in the last 30 days"
        )

    def test_lifecycle_first_time_action(self):
        action = self.action
        prop = Property(
            type="behavioral",
            value="performed_event_first_time",
            key=str(action.id),
            event_type="actions",
            time_value=1,
            time_interval="month",
            negation=True,
        )
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == f"people who did not perform the action `Completed onboarding` with ID `{action.id}` for the first time in the last 1 month"
        )

    def test_lifecycle_regular_event(self):
        prop = Property(
            type="behavioral",
            value="performed_event_regularly",
            key="contacted support",
            event_type="events",
            negation=False,
            operator="gte",
            operator_value=5,
            time_value=1,
            time_interval="day",
            min_periods=3,
            total_periods=6,
        )
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who performed the event `contacted support` at least 5 times per 1 day for at least 3 times in any of the last 6 periods"
        )

    def test_lifecycle_regular_event_once_values(self):
        prop = Property(
            type="behavioral",
            value="performed_event_regularly",
            key="contacted support",
            event_type="events",
            negation=True,
            operator="lte",
            operator_value=1,
            time_value=1,
            time_interval="month",
            min_periods=1,
            total_periods=1,
        )
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who did not perform the event `contacted support` at most once per 1 month for at least once in the last period"
        )

    def test_lifecycle_stopped_performing_event(self):
        prop = Property(
            type="behavioral",
            value="stopped_performing_event",
            key="contacted support",
            event_type="events",
            time_value=4,
            time_interval="week",
            seq_time_value=2,
            seq_time_interval="week",
            negation=False,
        )
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who stopped doing the event `contacted support` in the last 2 weeks but had done it in the last 4 weeks prior now"
        )
        prop.negation = True
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who did the event `contacted support` in the last 2 weeks but had done it in the last 4 weeks prior now"
        )

    def test_lifecycle_restarted_performing_event(self):
        prop = Property(
            type="behavioral",
            value="restarted_performing_event",
            key="contacted support",
            event_type="events",
            time_value=4,
            time_interval="week",
            seq_time_value=2,
            seq_time_interval="week",
            negation=False,
        )
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who started doing the event `contacted support` again in the last 2 weeks but had not done it in the last 4 weeks prior now"
        )
        prop.negation = True
        assert (
            CohortPropertySummarizer(self.team, prop).summary
            == "people who did not start doing the event `contacted support` again in the last 2 weeks but had not done it in the last 4 weeks prior now"
        )


class TestCohortPropertyGroupDescriber(BaseTest):
    def setUp(self):
        self.cond_1 = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event",
            negation=True,
            event_type="events",
            explicit_datetime="2025-03-10",
        )
        self.summary_1 = "people who did not complete the event `$pageview` on 2025-03-10"
        self.cond_2 = Property(
            key="$pageview",
            type="event",
            value="Homepage",
            operator="icontains",
        )
        self.summary_2 = "people who have the event property `$pageview` that contains `Homepage`"

    def test_cohort_property_group_describer_inline(self):
        prop_group = PropertyGroup(
            type=PropertyOperatorType.OR,
            values=[self.cond_1, self.cond_2],
        )
        assert (
            CohortPropertyGroupSummarizer(self.team, prop_group, inline_conditions=True).summary
            == f"({self.summary_1} OR {self.summary_2})"
        )

        prop_group = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[self.cond_1, self.cond_2],
        )
        assert (
            CohortPropertyGroupSummarizer(self.team, prop_group, inline_conditions=True).summary
            == f"({self.summary_1} AND {self.summary_2})"
        )

    def test_cohort_property_group_describer_multiline(self):
        prop_group = PropertyGroup(
            type=PropertyOperatorType.OR,
            values=[self.cond_1, self.cond_2],
        )
        assert (
            CohortPropertyGroupSummarizer(self.team, prop_group, inline_conditions=False).summary
            == f"{self.summary_1}\n\nOR\n\n{self.summary_2}"
        )

        prop_group = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[self.cond_1, self.cond_2],
        )
        assert (
            CohortPropertyGroupSummarizer(self.team, prop_group, inline_conditions=False).summary
            == f"{self.summary_1}\n\nAND\n\n{self.summary_2}"
        )

    def test_cohort_property_group_describer_nested_groups(self):
        prop_group_1 = PropertyGroup(
            type=PropertyOperatorType.OR,
            values=[self.cond_1, self.cond_2],
        )
        prop_group_2 = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[self.cond_1, self.cond_2],
        )
        prop_group_3 = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[prop_group_1, prop_group_2],
        )

        assert (
            CohortPropertyGroupSummarizer(self.team, prop_group_3, inline_conditions=True).summary
            == f"(({self.summary_1} OR {self.summary_2}) AND ({self.summary_1} AND {self.summary_2}))"
        )

        assert (
            CohortPropertyGroupSummarizer(self.team, prop_group_3, inline_conditions=False).summary
            == f"({self.summary_1} OR {self.summary_2})\n\nAND\n\n({self.summary_1} AND {self.summary_2})"
        )


class TestCohortSummarizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.cond_1 = Property(
            key="$pageview",
            type="behavioral",
            value="performed_event",
            negation=True,
            event_type="events",
            explicit_datetime="2025-03-10",
        )
        self.summary_1 = "people who did not complete the event `$pageview` on 2025-03-10"
        self.cond_2 = Property(
            key="$pageview",
            type="event",
            value="Homepage",
            operator="icontains",
        )
        self.summary_2 = "people who have the event property `$pageview` that contains `Homepage`"

        self.cohort = Cohort.objects.create(
            team=self.team,
            name="Visited homepage",
            description="The launch date of the product",
            filters={
                "properties": PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[self.cond_1, self.cond_2],
                ).to_dict(),
            },
        )

    def test_inline_cohort_summarizer(self):
        summarizer = CohortSummarizer(self.team, self.cohort, inline_conditions=True)
        assert (
            summarizer.summary
            == f"dynamic cohort `Visited homepage` with ID `{self.cohort.id}` described as `The launch date of the product` having the following filters ({self.summary_1} AND {self.summary_2})"
        )

    def test_multiline_cohort_summarizer(self):
        summarizer = CohortSummarizer(self.team, self.cohort, inline_conditions=False)
        summary = dedent(
            f"""
            Name: Visited homepage
            Description: The launch date of the product
            Type: Dynamic (based on filters)
            Filters:
            {self.summary_1}

            AND

            {self.summary_2}
            """
        )
        assert summarizer.summary == dedent(summary.strip())
