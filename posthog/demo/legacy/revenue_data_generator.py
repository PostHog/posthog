import random

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Dashboard, DashboardTile, EventDefinition, Insight, Person, PropertyDefinition

from .data_generator import DataGenerator


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
                event="entered_free_trial",
                distinct_id=distinct_id,
                timestamp=now() - relativedelta(days=345),
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
        purchase_action = Action.objects.create(team=self.team, name="Purchase", steps_json=[{"event": "purchase"}])

        Action.objects.create(team=self.team, name="Entered Free Trial", steps_json=[{"event": "entered_free_trial"}])

        dashboard = Dashboard.objects.create(name="Sales & Revenue", pinned=True, team=self.team)
        insight = Insight.objects.create(
            team=self.team,
            name="Entered Free Trial -> Purchase (Premium)",
            filters={
                "events": [
                    {
                        "id": "$pageview",
                        "name": "Pageview",
                        "order": 0,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    }
                ],
                "actions": [
                    {
                        "id": purchase_action.id,
                        "name": "Purchase",
                        "order": 1,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                        "properties": {"plan": "premium"},
                    }
                ],
                "insight": "FUNNELS",
                "date_from": "all",
            },
            short_id="TEST1234",
        )
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        dashboard.save()  # to update the insight's filter hash
