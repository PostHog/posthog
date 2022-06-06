import logging
from time import time

from django.core import exceptions
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from posthog.demo.hedgebox import HedgeboxMatrix
from posthog.demo.matrix.manager import MatrixManager

logging.getLogger("kafka").setLevel(logging.WARNING)  # Hide kafka-python's logspam


class Command(BaseCommand):
    help = "Rehearse demo data simulation"

    def add_arguments(self, parser):
        parser.add_argument(
            "--save-as",
            type=str,
            help="Email of the account that should be created to save the results of the simulation (the password: 12345678)",
        )
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")
        parser.add_argument(
            "--start",
            type=lambda s: timezone.make_aware(timezone.datetime.strptime(s, "%Y-%m-%d")),
            help="Simulation start date (default: 120 days ago)",
        )
        parser.add_argument(
            "--end",
            type=lambda s: timezone.make_aware(timezone.datetime.strptime(s, "%Y-%m-%d")),
            help="Simulation end date (default: today)",
        )
        parser.add_argument("--n-clusters", type=int, default=50, help="Number of clusters (default: 50)")
        parser.add_argument("--list-events", action="store_true", help="Print events individually")

    def handle(self, *args, **options):
        timer = time()
        matrix = HedgeboxMatrix(
            options["seed"],
            start=options["start"] or timezone.now() - timezone.timedelta(120),
            end=options["end"] or timezone.now(),
            n_clusters=options["n_clusters"],
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
        if email := options["save_as"]:
            print(f"Saving data as {email}…")
            with transaction.atomic():
                try:
                    MatrixManager(matrix, pre_save=False).ensure_account_and_save(
                        email, "Employee 427", "Hedgebox Inc.", password="12345678", disallow_collision=True
                    )
                except (exceptions.ValidationError, exceptions.PermissionDenied) as e:
                    print(str(e))
            print(f"{email} is ready!")
