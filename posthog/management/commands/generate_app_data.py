import random
import secrets
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import now

from ee.clickhouse.models.clickhouse import generate_clickhouse_uuid
from ee.clickhouse.models.event import create_event
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import (
    Action,
    ActionStep,
    Dashboard,
    DashboardItem,
    Event,
    Organization,
    Person,
    PersonDistinctId,
    Team,
)
from posthog.models.utils import UUIDT
from posthog.utils import recalculate_actions

SCREEN_OPTIONS = ("settings", "profile", "movies", "downloads")


def generate_app_data(org, team_name="", team_id=0, event_number=1000, days=100, use_ch=False, distinct_ids=[]):
    team = _get_team(org, team_name, team_id,)

    generate_data = _generate_ch_data if use_ch else _generate_psql_data
    generate_data(team, event_number, days, distinct_ids)

    if "watched_movie" not in team.event_names:
        team.event_names.append("watched_movie")
    if "installed_app" not in team.event_names:
        team.event_names.append("installed_app")
    if "rated_app" not in team.event_names:
        team.event_names.append("rated_app")
    if "$current_url" not in team.event_properties:
        team.event_properties.append("$current_url")
    if "is_first_movie" not in team.event_properties:
        team.event_properties.append("is_first_movie")
    if "app_rating" not in team.event_properties_numerical:
        team.event_properties_numerical.append("app_rating")

    team.save()

    if not use_ch:
        _create_psql_actions_and_funnel(team)


def _generate_psql_data(team, n_events, n_days, distinct_ids):
    if distinct_ids:
        distinct_ids = [ph_id.distinct_id for ph_id in distinct_ids]
    for i in range(0, n_events - len(distinct_ids)):
        distinct_id = str(UUIDT())
        app_rating = random.randint(1, 5)
        distinct_ids.append([distinct_id, app_rating])
        Person.objects.create(
            team=team, distinct_ids=[distinct_id], properties={"is_demo": True, "app_rating": app_rating}
        )

    events = []
    for i in range(0, n_events):
        n_days_back = random.randint(1, n_days)
        events.append(
            Event(
                event="$pageview",
                team=team,
                distinct_id=distinct_ids[i][0],
                timestamp=now() - relativedelta(days=n_days_back),
                properties={"$current_url": "https://hogflix/"},
            )
        )
        events.append(
            Event(
                event="installed_app",
                team=team,
                distinct_id=distinct_ids[i][0],
                timestamp=now() - relativedelta(days=n_days_back),
            )
        )
        if random.randint(0, 10) <= 9:
            events.append(
                Event(
                    event="watched_movie",
                    team=team,
                    distinct_id=distinct_ids[i][0],
                    timestamp=now() - relativedelta(days=n_days_back) + relativedelta(seconds=100),
                    properties={"is_first_movie": random.choice([True, False])},
                )
            )
            events.append(
                Event(
                    event="$pageview",
                    team=team,
                    distinct_id=distinct_ids[i][0],
                    timestamp=now() - relativedelta(days=n_days_back) + relativedelta(seconds=15),
                    properties={"$current_url": "https://hogflix/" + random.choice(SCREEN_OPTIONS)},
                )
            )
            if random.randint(0, 10) <= 8:
                events.append(
                    Event(
                        event="$pageview",
                        team=team,
                        distinct_id=distinct_ids[i][0],
                        timestamp=now() - relativedelta(days=n_days_back) + relativedelta(seconds=30),
                        properties={"$current_url": "https://hogflix/" + random.choice(SCREEN_OPTIONS)},
                    )
                )
                events.append(
                    Event(
                        event="rated_app",
                        team=team,
                        distinct_id=distinct_ids[i][0],
                        timestamp=now() - relativedelta(days=n_days_back) + relativedelta(seconds=45),
                        properties={"app_rating": distinct_ids[i][1]},
                    )
                )
    Event.objects.bulk_create(events)


def _create_psql_actions_and_funnel(team):
    installed_app_action = Action.objects.create(team=team, name="Installed App")
    ActionStep.objects.create(action=installed_app_action, event="installed_app")

    rated_app_action = Action.objects.create(team=team, name="Rated App")
    ActionStep.objects.create(action=rated_app_action, event="rated_app")

    watched_movie_action = Action.objects.create(team=team, name="Watched Movie")
    ActionStep.objects.create(action=watched_movie_action, event="watched_movie")

    dashboard = Dashboard.objects.create(
        name="App Analytics", pinned=True, team=team, share_token=secrets.token_urlsafe(22)
    )
    DashboardItem.objects.create(
        team=team,
        dashboard=dashboard,
        name="Installed App -> Rated App -> Rated App 5 Stars",
        type="FunnelViz",
        filters={
            "actions": [
                {"id": installed_app_action.id, "name": "Installed App", "order": 0, "type": TREND_FILTER_TYPE_ACTIONS},
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
    recalculate_actions(team)


def _generate_ch_data(team, n_events, n_days):
    pass


def _get_team(org, team_name, team_id):
    organization = Organization.objects.filter(name=org)[0]
    try:
        if team_name:
            team = organization.teams.filter(name=team_name)[0]
        else:
            team = organization.teams.filter(id=team_id)[0]
    except Team.DoesNotExist:
        team = Team.objects.create_with_data(
            organization=organization,
            name=team_name if team_name else "HogFlix Demo App",
            ingested_event=True,
            completed_snippet_onboarding=True,
        )
    return team


class Command(BaseCommand):
    help = "Bulk generate revenue data points for demos"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org", required=True, nargs=1, type=str, help="Name of the organization to create data for"
        )
        parser.add_argument("--team_name", nargs=1, type=str, help="Name of the team to create data for")
        parser.add_argument("--team_id", nargs=1, type=int, help="ID of the team to create data for")
        parser.add_argument("--event_number", nargs=1, type=int, help="Number of events to create")
        parser.add_argument("--days", nargs=1, type=int, help="Number of days events should be spread across")
        parser.add_argument(
            "--use_ch",
            nargs=1,
            type=bool,
            default=False,
            help="Override default and create data in ClickHouse instead of Postgres",
        )

    def handle(self, *args, **options):
        if not options["team_name"] and not options["team_id"]:
            print("You need to specify a --team_id or --team_name to run this command")
            exit(1)

        if not options["org"]:
            print("You need to specify an organization to run this command")
            exit(1)

        generate_app_data(
            org=options["org"][0],
            team_name=options["team_name"][0] if options["team_name"] else "",
            team_id=options["team_id"][0] if options["team_id"] else 0,
            event_number=options["event_number"][0] if options["event_number"] else 1000,
            days=options["days"][0] if options["days"] else 100,
            use_ch=options["use_ch"],
            distinct_ids=[],
        )
