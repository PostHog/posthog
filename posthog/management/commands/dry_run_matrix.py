import datetime as dt

from django.core.management.base import BaseCommand

from posthog.demo.hedgebox import HedgeboxMatrix


class Command(BaseCommand):
    help = "Rehearse demo data simulation"

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")

    def handle(self, *args, **options):
        matrix = HedgeboxMatrix(
            options["seed"], start=dt.datetime(2022, 2, 1), end=dt.datetime(2022, 5, 1), n_clusters=1
        )
        matrix.simulate()
        seen_people = [person for person in matrix.persons if person.first_seen_at is not None]
        print(f"Simulated {len(seen_people)} person{'s' if len(seen_people) != 1 else ''} with events")
        for person in seen_people:
            print()
            print(person)
            for event in person.events:
                print(event)
            print()
