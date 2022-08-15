from django.core.management.base import BaseCommand
from django.db import connection

from posthog.models import Person, Team


class Command(BaseCommand):
    help = "Merge users who have the same e-mail, but a different distinct_id"

    def add_arguments(self, parser):
        parser.add_argument("--team_id", nargs="+", type=int, help="specify the team id eg. --team_id 1")

    def handle(self, *args, **options):
        if not options["team_id"]:
            print("The argument --team_id is required")
            exit(1)

        for team in Team.objects.filter(pk__in=options["team_id"]):
            self._merge_team(team)

    def _merge_team(self, team):
        team_id = team.id

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select properties->>'email', team_id, count(*)
                from posthog_person
                where properties->>'email' is not null and properties->>'email' != '' and team_id = %s
                group by properties->>'email', team_id
                HAVING count(*) > 1
                order by count(*) desc;
                """,
                [team_id],
            )

            for row in cursor.fetchall():
                email = row[0]
                print(f"Merging email: {email}")

                people = Person.objects.filter(team=team, properties__email=email).order_by("pk")
                first_person = people[0]
                other_people = list(people[1:])

                first_person.merge_people(other_people)
