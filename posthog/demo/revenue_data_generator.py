import random
import secrets

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.demo.data_generator import DataGenerator, SimPerson
from posthog.models import (
    Action,
    ActionStep,
    Dashboard,
    EventDefinition,
    Insight,
    Person,
    PropertyDefinition,
    Team,
    User,
)


class RevenueDataGenerator(DataGenerator):
    def __init__(self, *, n_people: int = 100, n_days: int = 14):
        super().__init__(n_people=n_people, n_days=n_days)

    def _set_project_up(self, team: Team, user: User):
        EventDefinition.objects.get_or_create(team=team, name="purchase")
        EventDefinition.objects.get_or_create(team=team, name="entered_free_trial")
        PropertyDefinition.objects.get_or_create(team=team, name="plan")
        PropertyDefinition.objects.get_or_create(team=team, name="first_visit")
        PropertyDefinition.objects.get_or_create(team=team, name="purchase_value", is_numerical=True)
        purchase_action = Action.objects.create(team=team, name="Purchase")
        ActionStep.objects.create(action=purchase_action, event="purchase")

        free_trial_action = Action.objects.create(team=team, name="Entered Free Trial")
        ActionStep.objects.create(action=free_trial_action, event="entered_free_trial")

        dashboard = Dashboard.objects.create(
            name="Sales & Revenue", pinned=True, team=team, share_token=secrets.token_urlsafe(22)
        )
        Insight.objects.create(
            team=team,
            dashboard=dashboard,
            name="Entered Free Trial -> Purchase (Premium)",
            filters={
                "events": [{"id": "$pageview", "name": "Pageview", "order": 0, "type": TREND_FILTER_TYPE_ACTIONS,}],
                "actions": [
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

    def _create_person_with_journey(self, team: Team, user: User, index: int) -> SimPerson:
        person = SimPerson(team=team)
        person.properties["is_demo"] = True

        if random.randint(0, 10) <= 4:
            person.add_event(
                event="entered_free_trial", timestamp=now() - relativedelta(days=345),
            )

        person.add_event(
            event="$pageview", timestamp=now() - relativedelta(days=350), properties={"first_visit": True},
        )

        if random.randint(0, 100) < 72:
            base_days = random.randint(0, 29)
            for j in range(0, 11):
                plan, value = random.choice((("basic", 8), ("basic", 8), ("standard", 13), ("premium", 30)))
                person.add_event(
                    event="$pageview",
                    timestamp=now() - relativedelta(days=(j * 29 + base_days) if j == 0 else (j * 29 + base_days) - 1),
                )
                if random.randint(0, 10) <= 8:
                    person.add_event(
                        event="purchase",
                        properties={"plan": plan, "purchase_value": value},
                        timestamp=now() - relativedelta(days=j * 29 + base_days),
                    )
        return person
