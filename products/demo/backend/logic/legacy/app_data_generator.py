import random

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.schema import ActionsNode, DateRange, EventPropertyFilter, FunnelsQuery, InsightVizNode, PropertyOperator

from posthog.models import Person

from products.actions.backend.facade.api import create_action
from products.dashboards.backend.facade import api as dashboards_api
from products.event_definitions.backend.models import EventDefinition, PropertyDefinition
from products.product_analytics.backend.facade.models import Insight

from .data_generator import DataGenerator

SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


class AppDataGenerator(DataGenerator):
    def create_missing_events_and_properties(self):
        EventDefinition.objects.get_or_create(team=self.team, name="watched_movie")
        EventDefinition.objects.get_or_create(team=self.team, name="installed_app")
        EventDefinition.objects.get_or_create(team=self.team, name="rated_app")
        PropertyDefinition.objects.get_or_create(team=self.team, name="is_first_movie")
        PropertyDefinition.objects.get_or_create(team=self.team, name="app_rating", is_numerical=True)

    def create_actions_dashboards(self):
        installed_app_action = create_action(
            team=self.team, name="Installed App", steps_json=[{"event": "installed_app"}]
        )

        rated_app_action = create_action(team=self.team, name="Rated App", steps_json=[{"event": "rated_app"}])

        create_action(team=self.team, name="Watched Movie", steps_json=[{"event": "watched_movie"}])

        dashboard = dashboards_api.create_dashboard(name="App Analytics", pinned=True, team_id=self.team.id)
        insight = Insight.objects.create(
            team=self.team,
            name="Installed App -> Rated App -> Rated App 5 Stars",
            query=InsightVizNode(
                source=FunnelsQuery(
                    series=[
                        ActionsNode(id=installed_app_action.id, name="Installed App"),
                        ActionsNode(id=rated_app_action.id, name="Rated App"),
                        ActionsNode(
                            id=rated_app_action.id,
                            name="Rated App",
                            properties=[
                                EventPropertyFilter(key="app_rating", value=5, operator=PropertyOperator.EXACT)
                            ],
                        ),
                    ],
                    dateRange=DateRange(date_from="yStart"),
                )
            ).model_dump(),
        )
        dashboards_api.add_insight_tile(insight_id=insight.id, dashboard_id=dashboard.id)

    def populate_person_events(self, person: Person, distinct_id: str, _index: int):
        start_day = random.randint(1, self.n_days)
        self.add_event(
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=now() - relativedelta(days=start_day),
        )
        self.add_event(
            event="installed_app",
            distinct_id=distinct_id,
            timestamp=now() - relativedelta(days=start_day),
        )

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
