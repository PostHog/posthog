import random
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import now

from ee.clickhouse.models.clickhouse import generate_clickhouse_uuid
from ee.clickhouse.models.event import create_event
from posthog.models import Event, Organization, Person, PersonDistinctId, Team
from posthog.models.utils import UUIDT

PRICING_TIERS = [("basic", 10), ("growth", 20), ("premium", 30)]

# Note: Python's built-in hash function is not deterministic across runtimes
# But it is enough for this implementation
def _deterministic_random_value(payload, max_val=3):
    return hash(payload) % max_val


class Command(BaseCommand):
    help = "Bulk generate revenue data points for demos"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org", required=True, nargs=1, type=str, help="Name of the organization to create data for"
        )
        parser.add_argument("--team_name", nargs=1, type=str, help="Name of the team to create data for")
        parser.add_argument("--team_id", nargs=1, type=int, help="ID of the team to create data for")
        parser.add_argument("--event_number", nargs=1, type=int, default=10000, help="Number of events to create")
        parser.add_argument(
            "--days", nargs=1, type=int, default=100, help="Number of days events should be spread across"
        )
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

        team = self._get_team(
            options["org"][0],
            options["team_name"][0] if options["team_name"] else "",
            options["team_id"][0] if options["team_id"] else 0,
        )
        if options["use_ch"]:
            self._generate_ch_data(team, options["event_number"], options["days"])
        else:
            self._generate_psql_data(team, options["event_number"], options["days"])

        team.event_names.append("$purchase")
        team.event_properties.append("plan")
        team.event_properties_numerical.append("purchase_value")
        team.save()

    def _generate_psql_data(self, team, n_events, n_days):
        distinct_ids = []
        for i in range(0, n_events):
            distinct_id = str(UUIDT())
            distinct_ids.append(distinct_id)
            Person.objects.create(team=team, distinct_ids=[distinct_id], properties={"is_demo": True})

        Event.objects.bulk_create(
            Event(
                event="$purchase",
                team=team,
                distinct_id=distinct_ids[i],
                properties={
                    "plan": PRICING_TIERS[_deterministic_random_value(distinct_ids[i])][0],
                    "purchase_value": PRICING_TIERS[_deterministic_random_value(distinct_ids[i])][1],
                },
                timestamp=now() - relativedelta(days=random.randint(0, n_days)),
            )
            for i in range(0, n_events)
        )

    def _generate_ch_data(self, team, n_events, n_days):
        distinct_ids = []
        for i in range(0, n_events):
            distinct_id = generate_clickhouse_uuid()
            distinct_ids.append(distinct_id)
            Person.objects.create(team=team, distinct_ids=[distinct_id], properties={"is_demo": True})

        for i in range(0, n_events):
            event_uuid = uuid4()
            plan = random.choice(PRICING_TIERS)
            create_event(
                event="$purchase",
                team=team,
                distinct_id=distinct_ids[i],
                properties={"plan": plan[0], "purchase_value": plan[1],},
                timestamp=now() - relativedelta(days=random.randint(0, n_days)),
                event_uuid=event_uuid,
            )

    def _get_team(self, org, team_name, team_id):
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
                is_demo=True,
            )
        return team
