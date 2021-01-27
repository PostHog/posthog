import json
import random
import secrets
from pathlib import Path
from typing import Dict, List

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from rest_framework.request import Request

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.ee import is_ee_enabled
from posthog.models import (
    Action,
    ActionStep,
    Dashboard,
    DashboardItem,
    Element,
    Event,
    FeatureFlag,
    Organization,
    Person,
    PersonDistinctId,
    Team,
    User,
)
from posthog.models.utils import UUIDT
from posthog.utils import render_template

ORGANIZATION_NAME = "HogFlix"
TEAM_NAME = "HogFlix Demo App"
SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


def demo(request: Request):
    user = request.user
    organization = user.organization
    try:
        team = organization.teams.get(is_demo=True)
    except Team.DoesNotExist:
        team = create_demo_team(organization, user, request)
    user.current_team = team
    user.save()

    if "$pageview" not in team.event_names:
        team.event_names.append("$pageview")
        team.event_names_with_usage.append({"event": "$pageview", "usage_count": None, "volume": None})
        team.save()

    if is_ee_enabled():  # :TRICKY: Lazily backfill missing event data.
        from ee.clickhouse.models.event import get_events_by_team

        result = get_events_by_team(team_id=team.pk)
        if not result:
            AppDemoDataCreator(team, n_people=100).create()
            RevenueDemoDataCreator(team, n_people=20).create()

    return render_template("demo.html", request=request, context={"api_token": team.api_token})


def create_demo_team(organization: Organization, user: User, request: Request) -> Team:
    team = Team.objects.create_with_data(
        organization=organization, name=TEAM_NAME, ingested_event=True, completed_snippet_onboarding=True, is_demo=True,
    )
    AppDemoDataCreator(team, n_people=100).create()
    RevenueDemoDataCreator(team, n_people=20).create()

    return team


def _recalculate(team: Team) -> None:
    actions = Action.objects.filter(team=team)
    for action in actions:
        action.calculate_events()


class AppDemoDataCreator:
    def __init__(self, team: Team, n_days=14, n_people=100):
        self.team = team
        self.n_days = n_days
        self.n_people = n_people
        self.events = []
        self.distinct_ids = []

    def create(self):
        self.create_missing_events_and_properties()
        self.create_people()

        for index, (person, distinct_id) in enumerate(zip(self.people, self.distinct_ids)):
            self.populate_person_events(person, distinct_id, index)

        self.bulk_import_events()
        self.create_actions_dashboards()
        _recalculate(team=self.team)

    def create_people(self):
        self.people = [Person(team=self.team, properties={"is_demo": True}) for _ in range(self.n_people)]
        self.distinct_ids = [str(UUIDT()) for _ in self.people]

        Person.objects.bulk_create(self.people)
        PersonDistinctId.objects.bulk_create(
            [
                PersonDistinctId(team=self.team, person=person, distinct_id=distinct_id)
                for person, distinct_id in zip(self.people, self.distinct_ids)
            ]
        )

    def create_missing_events_and_properties(self):
        self.add_if_not_contained(self.team.event_names, "watched_movie")
        self.add_if_not_contained(self.team.event_names, "installed_app")
        self.add_if_not_contained(self.team.event_names, "rated_app")
        self.add_if_not_contained(self.team.event_properties, "$current_url")
        self.add_if_not_contained(self.team.event_properties, "is_first_movie")
        self.add_if_not_contained(self.team.event_properties_numerical, "app_rating")

        self.team.save()

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
        DashboardItem.objects.create(
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

    def bulk_import_events(self):
        if is_ee_enabled():
            from ee.clickhouse.demo import bulk_create_events

            bulk_create_events(self.events, team=self.team)
        else:
            Event.objects.bulk_create([Event(**kw, team=self.team) for kw in self.events])

    def add_event(self, **kw):
        self.events.append(kw)

    def add_if_not_contained(self, array, value):
        if value not in array:
            array.append(value)


class RevenueDemoDataCreator(AppDemoDataCreator):
    def create_missing_events_and_properties(self):
        self.add_if_not_contained(self.team.event_names, "purchase")
        self.add_if_not_contained(self.team.event_names, "entered_free_trial")
        self.add_if_not_contained(self.team.event_properties, "plan")
        self.add_if_not_contained(self.team.event_properties, "first_visit")
        self.add_if_not_contained(self.team.event_properties_numerical, "purchase_value")

        self.team.save()

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
                        properties={"plan": plan, "purchase_value": value,},
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
        DashboardItem.objects.create(
            team=self.team,
            dashboard=dashboard,
            name="Entered Free Trial -> Purchase (Premium)",
            filters={
                "actions": [
                    {
                        "id": free_trial_action.id,
                        "name": "Installed App",
                        "order": 0,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    {
                        "id": purchase_action.id,
                        "name": "Rated App",
                        "order": 1,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                        "properties": {"plan": "premium"},
                    },
                ],
                "insight": "FUNNELS",
                "date_from": "all",
            },
        )
