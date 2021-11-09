import random
import secrets

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.demo.data_generator import DataGenerator
from posthog.models import Action, ActionStep, Dashboard, EventDefinition, Insight, Person, PropertyDefinition

SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


class AppDataGenerator(DataGenerator):
    def create_missing_events_and_properties(self):
        EventDefinition.objects.get_or_create(team=self.team, name="watched_movie")
        EventDefinition.objects.get_or_create(team=self.team, name="installed_app")
        EventDefinition.objects.get_or_create(team=self.team, name="rated_app")
        PropertyDefinition.objects.get_or_create(team=self.team, name="is_first_movie")
        PropertyDefinition.objects.get_or_create(team=self.team, name="app_rating", is_numerical=True)

    def create_actions_dashboards(self):
        installed_app_action = Action.objects.create(team=self.team, name="Installed App")
        ActionStep.objects.create(action=installed_app_action, event="installed_app")

        rated_app_action = Action.objects.create(team=self.team, name="Rated App")
        ActionStep.objects.create(action=rated_app_action, event="rated_app")

        watched_movie_action = Action.objects.create(team=self.team, name="Watched Movie")
        ActionStep.objects.create(action=watched_movie_action, event="watched_movie")

        dashboard = Dashboard.objects.create(
            name="App Analytics", pinned=True, team=self.team, share_token=secrets.token_urlsafe(22)
        )
        Insight.objects.create(
            team=self.team,
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

    def populate_person_events(self, person: Person, distinct_id: str, _index: int):
        start_day = random.randint(1, self.n_days)
        self.add_event(event="$pageview", distinct_id=distinct_id, timestamp=now() - relativedelta(days=start_day))
        self.add_event(event="installed_app", distinct_id=distinct_id, timestamp=now() - relativedelta(days=start_day))

        if random.randint(0, 10) <= 9:
            self.add_event(
                event="watched_movie",
                distinct_id=distinct_id,
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=100),
                properties={"is_first_movie": random.choice([True, False])},
            )
            self.add_event(
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=15),
                properties={"$current_url": "https://hogflix/" + random.choice(SCREEN_OPTIONS)},
            )
            if random.randint(0, 10) <= 8:
                self.add_event(
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=30),
                    properties={"$current_url": "https://hogflix/" + random.choice(SCREEN_OPTIONS)},
                )
                self.add_event(
                    event="rated_app",
                    distinct_id=distinct_id,
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=45),
                    properties={"app_rating": random.randint(1, 5)},
                )
