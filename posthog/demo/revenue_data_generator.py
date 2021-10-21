import random
import secrets

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.demo.data_generator import DataGenerator
from posthog.models import Action, ActionStep, Dashboard, EventDefinition, Insight, Person, PropertyDefinition


class RevenueDataGenerator(DataGenerator):
    def create_missing_events_and_properties(self):
        EventDefinition.objects.get_or_create(team=self.team, name="purchase")
        EventDefinition.objects.get_or_create(team=self.team, name="entered_free_trial")
        PropertyDefinition.objects.get_or_create(team=self.team, name="plan")
        PropertyDefinition.objects.get_or_create(team=self.team, name="first_visit")
        PropertyDefinition.objects.get_or_create(team=self.team, name="purchase_value", is_numerical=True)

    def populate_person_events(self, person: Person, distinct_id: str, index: int):
        if random.randint(0, 10) <= 4:
            self.add_event(
                event="entered_free_trial", distinct_id=distinct_id, timestamp=now() - relativedelta(days=345),
            )

        self.add_event(
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=now() - relativedelta(days=350),
            properties={"first_visit": True},
        )

        if random.randint(0, 100) < 72:
            base_days = random.randint(0, 29)
            for j in range(0, 11):
                plan, value = random.choice((("basic", 8), ("basic", 8), ("standard", 13), ("premium", 30)))
                self.add_event(
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=now() - relativedelta(days=(j * 29 + base_days) if j == 0 else (j * 29 + base_days) - 1),
                )
                if random.randint(0, 10) <= 8:
                    self.add_event(
                        event="purchase",
                        distinct_id=distinct_id,
                        properties={"plan": plan, "purchase_value": value},
                        timestamp=now() - relativedelta(days=j * 29 + base_days),
                    )

    def create_actions_dashboards(self):
        purchase_action = Action.objects.create(team=self.team, name="Purchase")
        ActionStep.objects.create(action=purchase_action, event="purchase")

        free_trial_action = Action.objects.create(team=self.team, name="Entered Free Trial")
        ActionStep.objects.create(action=free_trial_action, event="entered_free_trial")

        dashboard = Dashboard.objects.create(
            name="Sales & Revenue", pinned=True, team=self.team, share_token=secrets.token_urlsafe(22)
        )
        Insight.objects.create(
            team=self.team,
            dashboard=dashboard,
            name="Entered Free Trial -> Purchase (Premium)",
            filters={
                "actions": [
                    {
                        "id": free_trial_action.id,
                        "name": "Entered Free Trial",
                        "order": 0,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    {
                        "id": purchase_action.id,
                        "name": "Purchase",
                        "order": 1,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                        "properties": {"plan": "premium"},
                    },
                ],
                "insight": "FUNNELS",
                "date_from": "all",
            },
            short_id="TEST1234",
        )
