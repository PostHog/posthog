import random
import secrets
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import now

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

# Add basic twice for weighting when using random.choice
PRICING_TIERS = (("basic", 8), ("basic", 8), ("standard", 13), ("premium", 30))


def generate_revenue_data(org, team_name="", team_id=0, event_number=1000, days=100, use_ch=False, distinct_ids=[]):
    team = _get_team(org, team_name, team_id,)

    generate_data = _generate_ch_data if use_ch else _generate_psql_data
    generate_data(team, event_number, days, distinct_ids)

    if "purchase" not in team.event_names:
        team.event_names.append("purchase")
    if "entered_free_trial" not in team.event_names:
        team.event_names.append("entered_free_trial")
    if "plan" not in team.event_properties:
        team.event_properties.append("plan")
    if "first_visit" not in team.event_properties:
        team.event_properties.append("first_visit")
    if "purchase_value" not in team.event_properties_numerical:
        team.event_properties_numerical.append("purchase_value")

    team.save()
    _create_actions_and_funnel(team)


def _generate_psql_data(team, n_events, n_days, distinct_ids):
    if distinct_ids:
        distinct_ids = [ph_id.distinct_id for ph_id in distinct_ids]
    for i in range(0, n_events - len(distinct_ids)):
        distinct_id = str(UUIDT())
        distinct_ids.append(distinct_id)
        Person.objects.create(team=team, distinct_ids=[distinct_id], properties={"is_demo": True})

    events = []
    for i in range(0, n_events):
        if random.randint(0, 10) <= 4:
            events.append(
                Event(
                    event="entered_free_trial",
                    team=team,
                    distinct_id=distinct_ids[i],
                    timestamp=now() - relativedelta(days=345),
                )
            )
        events.append(
            Event(
                event="$pageview",
                team=team,
                distinct_id=distinct_ids[i],
                timestamp=now() - relativedelta(days=350),
                properties={"first_visit": True},
            )
        )

    days_ago_options = ()
    for n in range(0, int(n_events * 0.72)):
        base_days = random.randint(0, 29)
        for j in range(0, 11):
            plan = random.choice(PRICING_TIERS)
            events.append(
                Event(
                    event="$pageview",
                    team=team,
                    distinct_id=distinct_ids[n],
                    timestamp=now() - relativedelta(days=(j * 29 + base_days) if j == 0 else (j * 29 + base_days) - 1),
                )
            )
            if random.randint(0, 10) <= 8:
                events.append(
                    Event(
                        event="purchase",
                        team=team,
                        distinct_id=distinct_ids[n],
                        properties={"plan": plan[0], "purchase_value": plan[1],},
                        timestamp=now() - relativedelta(days=j * 29 + base_days),
                    )
                )
    Event.objects.bulk_create(events)


def _generate_ch_data(team, n_events, n_days, distinct_ids=[]):
    from ee.clickhouse.models.clickhouse import generate_clickhouse_uuid
    from ee.clickhouse.models.event import create_event

    for i in range(0, n_events - len(distinct_ids)):
        distinct_id = generate_clickhouse_uuid()
        distinct_ids.append(distinct_id)
        Person.objects.create(team=team, distinct_ids=[distinct_id], properties={"is_demo": True})

    for i in range(0, n_events):
        if random.randint(0, 10) <= 4:
            create_event(
                event="entered_free_trial",
                team=team,
                distinct_id=distinct_ids[i],
                timestamp=now() - relativedelta(days=345),
                event_uuid=uuid4(),
            )

        create_event(
            event="$pageview",
            team=team,
            distinct_id=distinct_ids[i],
            timestamp=now() - relativedelta(days=350),
            properties={"first_visit": True},
            event_uuid=uuid4(),
        )

    days_ago_options = ()
    for n in range(0, int(n_events * 0.72)):
        base_days = random.randint(0, 29)
        for j in range(0, 11):
            plan = random.choice(PRICING_TIERS)
            create_event(
                event="$pageview",
                team=team,
                distinct_id=distinct_ids[n],
                timestamp=now() - relativedelta(days=(j * 29 + base_days) if j == 0 else (j * 29 + base_days) - 1),
                event_uuid=uuid4(),
            )
            if random.randint(0, 10) <= 8:
                create_event(
                    event="purchase",
                    team=team,
                    distinct_id=distinct_ids[n],
                    properties={"plan": plan[0], "purchase_value": plan[1],},
                    timestamp=now() - relativedelta(days=j * 29 + base_days),
                    event_uuid=uuid4(),
                )


def _create_actions_and_funnel(team):
    purchase_action = Action.objects.create(team=team, name="Purchase")
    ActionStep.objects.create(action=purchase_action, event="purchase")

    free_trial_action = Action.objects.create(team=team, name="Entered Free Trial")
    ActionStep.objects.create(action=free_trial_action, event="entered_free_trial")

    dashboard = Dashboard.objects.create(
        name="Sales & Revenue", pinned=True, team=team, share_token=secrets.token_urlsafe(22)
    )
    DashboardItem.objects.create(
        team=team,
        dashboard=dashboard,
        name="Entered Free Trial -> Purchase (Premium)",
        type="FunnelViz",
        filters={
            "actions": [
                {"id": free_trial_action.id, "name": "Installed App", "order": 0, "type": TREND_FILTER_TYPE_ACTIONS},
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
    recalculate_actions(team)


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

        generate_revenue_data(
            org=options["org"][0],
            team_name=options["team_name"][0] if options["team_name"] else "",
            team_id=options["team_id"][0] if options["team_id"] else 0,
            event_number=options["event_number"][0] if options["event_number"] else 1000,
            days=options["days"][0] if options["days"] else 100,
            use_ch=options["use_ch"],
            distinct_ids=[],
        )


# docker exec ee_web_1 DEBUG=1 python3 manage.py generate_revenue_data --org="Demo" --team_name="HogFlix Demo App" —event_number=300 --use_ch=True
