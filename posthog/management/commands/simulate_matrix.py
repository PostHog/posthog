import datetime as dt
from time import time

from django.core.management.base import BaseCommand

from posthog.demo.hedgebox import HedgeboxMatrix


class Command(BaseCommand):
    help = "Rehearse demo data simulation"

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=str, required=True, help="Simulation seed for deterministic output")
        parser.add_argument(
            "--start", type=lambda s: dt.datetime.strptime(s, "%Y-%m-%d"), required=True, help="Simulation start date"
        )
        parser.add_argument(
            "--end", type=lambda s: dt.datetime.strptime(s, "%Y-%m-%d"), required=True, help="Simulation end date"
        )
        parser.add_argument("--n-clusters", type=int, default=1, help="Number of clusters")

    def handle(self, *args, **options):
        timer = time()
        matrix = HedgeboxMatrix(
            options["seed"], start=options["start"], end=options["end"], n_clusters=options["n_clusters"],
        )
        matrix.simulate()
        duration = time() - timer
        for cluster in matrix.clusters:
            print(
                f"Cluster {cluster.index}: {cluster}. Radius = {cluster.radius}. Population = {len(cluster.people_matrix) * len(cluster.people_matrix[0])}."
            )
            for y, person_row in enumerate(cluster.people_matrix):
                for x, person in enumerate(person_row):
                    print(f"    Person {x, y}: {person}")
                    active_session_id = None
                    for event in person.events:
                        if session_id := event.properties.get("$session_id"):
                            if active_session_id != session_id:
                                print(f"        Session {session_id}:")
                            active_session_id = session_id
                        print(f"            {event}")
        print(
            f"All in all, simulated {len(matrix.people)} {'person' if len(matrix.people) == 1 else 'people'} within {len(matrix.clusters)} cluster{'' if len(matrix.clusters) == 1 else 's'} in {round(duration * 1000)} ms."
        )
