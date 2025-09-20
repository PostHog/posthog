import json
import random
from datetime import timedelta
from typing import Any

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import Action, Dashboard, DashboardTile, Insight, Person, PropertyDefinition
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.utils import UUIDT
from posthog.utils import get_absolute_path

from .data_generator import DataGenerator

SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


class WebDataGenerator(DataGenerator):
    def create_missing_events_and_properties(self):
        self.add_if_not_contained(self.team.event_properties_numerical, "purchase")
        self.add_if_not_contained(self.team.event_properties, "purchase")
        PropertyDefinition.objects.get_or_create(team=self.team, name="purchase", is_numerical=True)
        PropertyDefinition.objects.get_or_create(team=self.team, name="$current_url")
        PropertyDefinition.objects.get_or_create(team=self.team, name="$browser")

    def create_actions_dashboards(self):
        homepage = Action.objects.create(
            team=self.team,
            name="Hogflix homepage view",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "http://hogflix.com",
                    "url_matching": "exact",
                }
            ],
        )

        user_signed_up = Action.objects.create(
            team=self.team,
            name="Hogflix signed up",
            steps_json=[
                {
                    "event": "$autocapture",
                    "url": "http://hogflix.com/1",
                    "url_matching": "contains",
                    "selector": "button",
                }
            ],
        )

        user_paid = Action.objects.create(
            team=self.team,
            name="Hogflix paid",
            steps_json=[
                {
                    "event": "$autocapture",
                    "url": "http://hogflix.com/2",
                    "url_matching": "contains",
                    "selector": "button",
                }
            ],
        )

        dashboard = Dashboard.objects.create(name="Web Analytics", pinned=True, team=self.team)
        insight = Insight.objects.create(
            team=self.team,
            name="Hogflix signup -> watching movie",
            description="Shows a conversion funnel from sign up to watching a movie.",
            filters={
                "actions": [
                    {
                        "id": homepage.id,
                        "name": "Hogflix homepage view",
                        "order": 0,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    {
                        "id": user_signed_up.id,
                        "name": "Hogflix signed up",
                        "order": 1,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    {
                        "id": user_paid.id,
                        "name": "Hogflix paid",
                        "order": 2,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                ],
                "insight": "FUNNELS",
            },
        )
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        dashboard.save()  # to update the insight's filter hash

    def populate_person_events(self, person: Person, distinct_id: str, index: int):
        start_day = random.randint(1, 7) if index > 0 else 0
        browser = random.choice(["Chrome", "Safari", "Firefox"])

        self.add_event(
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=now() - relativedelta(days=start_day),
            properties={
                "$current_url": "http://hogflix.com",
                "$browser": browser,
                "$lib": "web",
            },
        )

        self.add_event(
            distinct_id=distinct_id,
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
            self.add_event(
                event="$autocapture",
                distinct_id=distinct_id,
                properties={
                    "$current_url": "http://hogflix.com/1",
                    "$browser": browser,
                    "$lib": "web",
                    "$event_type": "click",
                },
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=29),
            )
            self.add_event(
                event="$pageview",
                distinct_id=distinct_id,
                properties={
                    "$current_url": "http://hogflix.com/2",
                    "$browser": browser,
                    "$lib": "web",
                },
                timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=30),
            )
            if index % 5 == 0:
                self.add_event(
                    event="$autocapture",
                    distinct_id=distinct_id,
                    properties={
                        "$current_url": "http://hogflix.com/2",
                        "$browser": browser,
                        "$lib": "web",
                        "$event_type": "click",
                    },
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=59),
                )
                self.add_event(
                    event="purchase",
                    distinct_id=distinct_id,
                    properties={"price": 10},
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=60),
                )
                self.add_event(
                    event="$pageview",
                    distinct_id=distinct_id,
                    properties={
                        "$current_url": "http://hogflix.com/3",
                        "$browser": browser,
                        "$lib": "web",
                    },
                    timestamp=now() - relativedelta(days=start_day) + relativedelta(seconds=60),
                )

    def populate_session_recording(self, person: Person, distinct_id: str, index: int):
        if index != 0:
            return

        date = now()
        start_time = self.demo_recording["result"]["snapshots"][0]["timestamp"]
        session_id = str(UUIDT())
        window_id = str(UUIDT())

        for snapshot in self.demo_recording["result"]["snapshots"]:
            self.snapshots.append(
                {
                    "session_id": session_id,
                    "window_id": window_id,
                    "distinct_id": distinct_id,
                    "timestamp": date + timedelta(milliseconds=snapshot["timestamp"] - start_time),
                    "snapshot_data": snapshot,
                }
            )

    def make_person(self, index):
        if index < len(self.demo_data):
            properties = self.demo_data[index]
            properties["is_demo"] = True
            return Person(team=self.team, properties=properties, is_identified=True)
        else:
            return super().make_person(index)

    @cached_property
    def demo_data(self) -> list[dict[str, Any]]:
        with open(get_absolute_path("demo/legacy/demo_people.json")) as demo_data_file:
            return json.load(demo_data_file)

    @cached_property
    def demo_recording(self) -> dict[str, Any]:
        with open(get_absolute_path("demo/legacy/hogflix_session_recording.json")) as demo_session_file:
            return json.load(demo_session_file)
