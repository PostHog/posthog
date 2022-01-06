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

SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


class AppDataGenerator(DataGenerator):
    def __init__(self, *, n_people: int = 100, n_days: int = 14):
        super().__init__(n_people=n_people, n_days=n_days)

    def _set_project_up(self, team: Team, user: User):
        EventDefinition.objects.get_or_create(team=team, name="watched_movie")
        EventDefinition.objects.get_or_create(team=team, name="installed_app")
        EventDefinition.objects.get_or_create(team=team, name="rated_app")
        PropertyDefinition.objects.get_or_create(team=team, name="is_first_movie")
        PropertyDefinition.objects.get_or_create(team=team, name="app_rating", is_numerical=True)

        installed_app_action = Action.objects.create(team=team, name="Installed App")
        ActionStep.objects.create(action=installed_app_action, event="installed_app")

        rated_app_action = Action.objects.create(team=team, name="Rated App")
        ActionStep.objects.create(action=rated_app_action, event="rated_app")

        watched_movie_action = Action.objects.create(team=team, name="Watched Movie")
        ActionStep.objects.create(action=watched_movie_action, event="watched_movie")

        dashboard = Dashboard.objects.create(
            name="App Analytics", pinned=True, team=team, share_token=secrets.token_urlsafe(22)
        )
        Insight.objects.create(
            team=team,
            dashboard=dashboard,
            name="Installed App -> Rated App -> Rated App 5 Stars",
            filters={
                "actions": [
                    {
                        "id": installed_app_action.id,
                        "name": "Installed App",
                        "order": 0,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    {"id": rated_app_action.id, "name": "Rated App", "order": 1, "type": TREND_FILTER_TYPE_ACTIONS,},
                    {
                        "id": rated_app_action.id,
                        "name": "Rated App",
                        "order": 2,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                        "properties": {"app_rating": 5},
                    },
                ],
                "insight": "FUNNELS",
                "date_from": "yStart",
            },
        )

    def _create_person_with_journey(self, team: Team, user: User, index: int) -> SimPerson:
        person = SimPerson(team=team)
        person.properties["is_demo"] = True

        start_day = random.randint(1, self.n_days)
        person.add_event(event="$pageview", timestamp=now() - relativedelta(days=start_day))
        person.add_event(event="installed_app", timestamp=now() - relativedelta(days=start_day))

        if random.randint(0, 10) <= 9:
            person.add_event(
                event="watched_movie",
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=100),
                properties={"is_first_movie": random.choice([True, False])},
            )
            person.add_event(
                event="$pageview",
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=15),
                properties={"$current_url": "https://hogflix/" + random.choice(SCREEN_OPTIONS)},
            )
            if random.randint(0, 10) <= 8:
                person.add_event(
                    event="$pageview",
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=30),
                    properties={"$current_url": "https://hogflix/" + random.choice(SCREEN_OPTIONS)},
                )
                person.add_event(
                    event="rated_app",
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=45),
                    properties={"app_rating": random.randint(1, 5)},
                )
        return person
