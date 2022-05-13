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
        parser.add_argument("--list-events", action="store_true", help="Print events individually")

    def handle(self, *args, **options):
        timer = time()
        matrix = HedgeboxMatrix(
            options["seed"], start=options["start"], end=options["end"], n_clusters=options["n_clusters"],
        )
        matrix.simulate()
        duration = time() - timer
        active_people_count = 0  # Active means they had at least one event
        total_event_count = 0
        for cluster in matrix.clusters:
            print(
                f"Cluster {cluster.index}: {cluster}. Radius = {cluster.radius}. Population = {len(cluster.people_matrix) * len(cluster.people_matrix[0])}."
            )
            for y, person_row in enumerate(cluster.people_matrix):
                for x, person in enumerate(person_row):
                    print(f"    Person {x, y}: {person}")
                    total_event_count += len(person.events)
                    if person.events:
                        active_people_count += 1
                    if options["list_events"]:
                        active_session_id = None
                        for event in person.events:
                            if session_id := event.properties.get("$session_id"):
                                if active_session_id != session_id:
                                    print(f"        Session {session_id}:")
                                active_session_id = session_id
                            print(f"            {event}")
                    else:
                        event_count = len(person.events)
                        if not event_count:
                            print("        No events")
                        else:
                            session_count = len(set(event.properties.get("$session_id") for event in person.events))
                            print(
                                f"        {event_count} event{'' if event_count == 1 else 's'} "
                                f"across {session_count} session{'' if session_count == 1 else 's'} "
                                f"between {person.events[0].timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"and {person.events[-1].timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
        print(
            f"All in all, in {duration * 1000:.2f} ms "
            f"simulated {len(matrix.people)} {'person' if len(matrix.people) == 1 else 'people'} "
            f"({active_people_count} active) "
            f"within {len(matrix.clusters)} cluster{'' if len(matrix.clusters) == 1 else 's'} "
            f"for a total of {total_event_count} event{'' if total_event_count == 1 else 's'}."
        )
