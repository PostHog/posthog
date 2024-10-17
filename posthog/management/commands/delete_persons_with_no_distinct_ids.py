from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team, Person, PersonDistinctId


class Command(BaseCommand):
    help = "Delete person rows that have no associated persondistinctid rows, by team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Team ID to migrate from (on this instance)")

    def handle(self, **options):
        team_id = options["team_id"]

        if not team_id:
            raise CommandError("source Team ID is required")

        team = Team.objects.get(pk=team_id)

        print("Deleting persons with no distinct ids for team", team_id)  # noqa: T201

        # There's a relationship from persondistinctid to person, but not in the other
        # direction, so we have to iterate over the entire person set to find the ones
        # that have no distinct ids
        people = Person.objects.filter(team=team)

        # Delete persons with no distinct ids
        deleted = 0
        for p in people:
            if not PersonDistinctId.objects.filter(person=p).exists():
                print(f"Deleting person {p} with no distinct ids")  # noqa: T201
                p.delete()
                deleted += 1

        print(f"Deleted {deleted} persons with no distinct ids")  # noqa: T201
