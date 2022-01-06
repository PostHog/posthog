import json
import random
import secrets
from datetime import timedelta
from typing import Any, Dict, List

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.demo.data_generator import DataGenerator, SimPerson
from posthog.models import Action, ActionStep, Dashboard, Insight, PropertyDefinition, Team, User
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.utils import UUIDT
from posthog.utils import get_absolute_path

SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


class WebDataGenerator(DataGenerator):
    def __init__(self, *, n_people: int = 100, n_days: int = 14):
        super().__init__(n_people=n_people, n_days=n_days)

    def _set_project_up(self, team: Team, user: User):
        if "purchase" not in team.event_properties_numerical:
            team.event_properties_numerical.append("purchase")
        if "purchase" not in team.event_properties:
            team.event_properties.append("purchase")
        PropertyDefinition.objects.get_or_create(team=team, name="purchase", is_numerical=True)
        PropertyDefinition.objects.get_or_create(team=team, name="$current_url")
        PropertyDefinition.objects.get_or_create(team=team, name="$browser")

        homepage = Action.objects.create(team=team, name="Hogflix homepage view")
        ActionStep.objects.create(action=homepage, event="$pageview", url="http://hogflix.com", url_matching="exact")

        user_signed_up = Action.objects.create(team=team, name="Hogflix signed up")
        ActionStep.objects.create(
            action=user_signed_up,
            event="$autocapture",
            url="http://hogflix.com/1",
            url_matching="contains",
            selector="button",
        )

        user_paid = Action.objects.create(team=team, name="Hogflix paid")
        ActionStep.objects.create(
            action=user_paid,
            event="$autocapture",
            url="http://hogflix.com/2",
            url_matching="contains",
            selector="button",
        )

        dashboard = Dashboard.objects.create(
            name="Web Analytics", pinned=True, team=team, share_token=secrets.token_urlsafe(22)
        )
        Insight.objects.create(
            team=team,
            dashboard=dashboard,
            name="Hogflix signup -> watching movie",
            description="Shows a conversion funnel from sign up to watching a movie.",
            filters={
                "actions": [
                    {"id": homepage.id, "name": "Hogflix homepage view", "order": 0, "type": TREND_FILTER_TYPE_ACTIONS},
                    {
                        "id": user_signed_up.id,
                        "name": "Hogflix signed up",
                        "order": 1,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    {"id": user_paid.id, "name": "Hogflix paid", "order": 2, "type": TREND_FILTER_TYPE_ACTIONS},
                ],
                "insight": "FUNNELS",
            },
        )

    def _create_person_with_journey(self, team: Team, user: User, index: int) -> SimPerson:
        person = SimPerson(team=team)
        if index < len(self.demo_data):
            person.properties.update(self.demo_data[index])
        person.properties["is_demo"] = True

        if index == 0:

            now_datetime = now()
            start_time = self.demo_recording["result"]["snapshots"][0]["timestamp"]
            session_id = str(UUIDT())
            window_id = str(UUIDT())

            for snapshot in self.demo_recording["result"]["snapshots"]:
                person.add_snapshot(
                    snapshot,
                    session_id,
                    window_id,
                    now_datetime + timedelta(milliseconds=snapshot["timestamp"] - start_time),
                )

        start_day = random.randint(1, 7) if index > 0 else 0
        browser = random.choice(["Chrome", "Safari", "Firefox"])

        person.add_event(
            event="$pageview",
            timestamp=now() - relativedelta(days=start_day),
            properties={"$current_url": "http://hogflix.com", "$browser": browser, "$lib": "web"},
        )

        person.add_event(
            event="$autocapture",
            properties={
                "$current_url": "http://hogflix.com",
                "$browser": browser,
                "$lib": "web",
                "$event_type": "click",
            },
            timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=14),
        )

        if index % 4 == 0:
            person.add_event(
                event="$autocapture",
                properties={
                    "$current_url": "http://hogflix.com/1",
                    "$browser": browser,
                    "$lib": "web",
                    "$event_type": "click",
                },
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=29),
            )
            person.add_event(
                event="$pageview",
                properties={"$current_url": "http://hogflix.com/2", "$browser": browser, "$lib": "web",},
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=30),
            )
            if index % 5 == 0:
                person.add_event(
                    event="$autocapture",
                    properties={
                        "$current_url": "http://hogflix.com/2",
                        "$browser": browser,
                        "$lib": "web",
                        "$event_type": "click",
                    },
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=59),
                )
                person.add_event(
                    event="purchase",
                    properties={"price": 10},
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=60),
                )
                person.add_event(
                    event="$pageview",
                    properties={"$current_url": "http://hogflix.com/3", "$browser": browser, "$lib": "web",},
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=60),
                )

        return person

    @cached_property
    def demo_data(self) -> List[Dict[str, Any]]:
        with open(get_absolute_path("demo/demo_data.json"), "r") as demo_data_file:
            return json.load(demo_data_file)

    @cached_property
    def demo_recording(self) -> Dict[str, Any]:
        with open(get_absolute_path("demo/hogflix_session_recording.json"), "r") as demo_session_file:
            return json.load(demo_session_file)
