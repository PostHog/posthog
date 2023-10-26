from ee.clickhouse.queries.experiments.utils import requires_flag_warning
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.action.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.filter import Filter
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from posthog.test.test_journeys import journeys_for


class TestUtils(ClickhouseTestMixin, APIBaseTest):
    def test_with_no_feature_flag_properties_on_events(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "user signed up", "properties": {"$os": "Windows"}},
                ],
                "person2": [
                    {"event": "user signed up", "properties": {"$os": "Windows"}},
                ],
            },
        )

        filter = Filter(
            data={
                "events": [{"id": "user signed up", "type": "events", "order": 0}],
                "insight": INSIGHT_FUNNELS,
            }
        )

        self.assertTrue(requires_flag_warning(filter, self.team))

    def test_with_feature_flag_properties_on_events(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {
                        "event": "user signed up",
                        "properties": {"$os": "Windows", "$feature/aloha": "control"},
                    },
                ],
                "person2": [
                    {
                        "event": "user signed up",
                        "properties": {"$os": "Windows", "$feature/aloha": "test"},
                    },
                ],
            },
        )

        filter = Filter(
            data={
                "events": [{"id": "user signed up", "type": "events", "order": 0}],
                "insight": INSIGHT_FUNNELS,
            }
        )

        self.assertFalse(requires_flag_warning(filter, self.team))

    def test_with_no_feature_flag_properties_on_actions(self):
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(
            action=action_credit_card,
            event="paid",
            properties=[
                {
                    "key": "$os",
                    "type": "event",
                    "value": ["Windows"],
                    "operator": "exact",
                }
            ],
        )

        ActionStep.objects.create(
            action=action_credit_card,
            event="$autocapture",
            tag_name="button",
            text="Pay $10",
        )

        filter = Filter(
            data={
                "events": [{"id": "user signed up", "type": "events", "order": 0}],
                "actions": [
                    {"id": action_credit_card.pk, "type": "actions", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
            }
        )

        journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "user signed up", "properties": {"$os": "Windows"}},
                    {"event": "paid", "properties": {"$os": "Windows"}},
                ],
                "person2": [
                    {"event": "paid", "properties": {"$os": "Windows"}},
                ],
                "person3": [
                    {"event": "user signed up", "properties": {"$os": "Windows"}},
                ],
            },
        )

        self.assertTrue(requires_flag_warning(filter, self.team))

    def test_with_feature_flag_properties_on_actions(self):
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(
            action=action_credit_card,
            event="paid",
            properties=[
                {
                    "key": "$os",
                    "type": "event",
                    "value": ["Windows"],
                    "operator": "exact",
                }
            ],
        )

        filter = Filter(
            data={
                "events": [{"id": "user signed up", "type": "events", "order": 0}],
                "actions": [
                    {"id": action_credit_card.pk, "type": "actions", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
            }
        )

        journeys_for(
            team=self.team,
            events_by_person={
                "person1": [
                    {"event": "user signed up", "properties": {"$os": "Windows"}},
                    {"event": "paid", "properties": {"$os": "Windows"}},
                ],
                "person2": [
                    {
                        "event": "paid",
                        "properties": {"$os": "Windows", "$feature/aloha": "test"},
                    },
                ],
                "person3": [
                    {"event": "user signed up", "properties": {"$os": "Windows"}},
                ],
            },
        )

        self.assertFalse(requires_flag_warning(filter, self.team))
