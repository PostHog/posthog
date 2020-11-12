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
    help = "Set up the instance for development/review with demo data"

    def add_arguments(self, parser):
        parser.add_argument("--org", nargs="+", type=str, help="Name of the organization to create data for")
        parser.add_argument("--team_name", nargs="+", type=str, help="Name of the team to create data for")
        parser.add_argument("--team_id", nargs="+", type=int, help="ID of the team to create data for")
        parser.add_argument(
            "--use_ch", nargs="+", type=bool, help="Override default and create data in ClickHouse instead of Postgres"
        )

    def handle(self, *args, **options):
        if not options["org"] or (not options["team_name"] and not options["team_id"]):
            if not options["org"]:
                print("The argument --org is required")
            else:
                print("You need to specify a --team_id or --team_name to run this command")
            exit(1)

        team = self._get_team(options["org"][0], options["team_name"], options["team_id"])
        if options["use_ch"]:
            self._generate_ch_data(team)
        else:
            self._generate_psql_data(team)

        team.event_names.append("$purchase")
        team.event_properties.append("plan")
        team.event_properties_numerical.append("purchase_value")
        team.save()

    def _generate_psql_data(self, team):
        distinct_ids = []
        for i in range(0, 10000):
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
                timestamp=now() - relativedelta(days=random.randint(0, 100)),
            )
            for i in range(0, 10000)
        )

    def _generate_ch_data(self, team):
        distinct_ids = []
        for i in range(0, 10000):
            distinct_id = generate_clickhouse_uuid()
            distinct_ids.append(distinct_id)
            Person.objects.create(team=team, distinct_ids=[distinct_id], properties={"is_demo": True})

        for i in range(0, 10000):
            event_uuid = uuid4()
            create_event(
                event="$purchase",
                team=team,
                distinct_id=distinct_ids[i],
                properties={
                    "plan": PRICING_TIERS[_deterministic_random_value(distinct_ids[i])][0],
                    "purchase_value": PRICING_TIERS[_deterministic_random_value(distinct_ids[i])][1],
                },
                timestamp=now() - relativedelta(days=random.randint(0, 100)),
                event_uuid=event_uuid,
            )

    def _get_team(self, org, team_name, team_id):
        organization = Organization.objects.filter(name=org)[0]
        try:
            if team_name:
                team = organization.teams.filter(name=team_name[0])[0]
            else:
                team = organization.teams.filter(id=team_id[0])[0]
        except Team.DoesNotExist:
            team = Team.objects.create_with_data(
                organization=organization,
                name=team_name if team_name else "HogFlix Demo App",
                ingested_event=True,
                completed_snippet_onboarding=True,
            )
        return team
