import datetime as dt
import logging
import secrets
from time import time
from typing import cast

from django.core import exceptions
from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo.matrix.manager import MatrixManager
from posthog.demo.matrix.models import SimEvent
from posthog.demo.products.hedgebox import HedgeboxMatrix

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
            "--now", type=dt.datetime.fromisoformat, help="Simulation 'now' datetime in ISO format (default: now)",
        )
        parser.add_argument(
            "--days-past",
            type=int,
            default=120,
            help="At how many days before 'now' should the simulation start (default: 120)",
        )
        parser.add_argument(
            "--days-future",
            type=int,
            default=30,
            help="At how many days after 'now' should the simulation end (default: 30)",
        )
        parser.add_argument("--n-clusters", type=int, default=50, help="Number of clusters (default: 50)")
        parser.add_argument("--list-events", action="store_true", help="Print events individually")

    def handle(self, *args, **options):
        timer = time()
        seed = options.get("seed") or secrets.token_hex(16)
        now = options.get("now") or dt.datetime.now(dt.timezone.utc)
        matrix = HedgeboxMatrix(
            seed,
            now=now,
            days_past=options["days_past"],
            days_future=options["days_future"],
            n_clusters=options["n_clusters"],
        )
        matrix.simulate()
        duration = time() - timer
        active_people_count = 0  # Active means they have at least one event
        total_event_count = 0
        future_event_count = 0
        summary_lines = [f"Matrix: {matrix.PRODUCT_NAME}. Seed: {seed}."]
        for cluster in matrix.clusters:
            summary_lines.append(
                f"    Cluster {cluster.index}: {cluster}. Radius = {cluster.radius}. Population = {len(cluster.people_matrix) * len(cluster.people_matrix[0])}.",
            )
            for y, person_row in enumerate(cluster.people_matrix):
                for x, person in enumerate(person_row):
                    summary_lines.append(f"        Person {x, y}: {person}",)
                    total_event_count += len(person.past_events) + len(person.future_events)
                    future_event_count += len(person.future_events)
                    if person.all_events:
                        active_people_count += 1
                    if options["list_events"]:
                        active_session_id = None
                        for event in person.all_events:
                            if session_id := event.properties.get("$session_id"):
                                if active_session_id != session_id:
                                    summary_lines.append(f"            Session {session_id}:",)
                                active_session_id = session_id
                            summary_lines.append(f"            {event}",)
                    else:
                        event_count = len(person.past_events) + len(person.future_events)
                        if not event_count:
                            summary_lines.append("            No events",)
                        else:
                            session_count = len(set(event.properties.get("$session_id") for event in person.all_events))
                            summary_lines.append(
                                f"            {event_count} event{'' if event_count == 1 else 's'} "
                                f"across {session_count} session{'' if session_count == 1 else 's'} "
                                f"between {cast(SimEvent, person.first_event).timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"and {cast(SimEvent, person.last_event).timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
                            )
        summary_lines.append(
            f"All in all, in {duration * 1000:.2f} ms "
            f"simulated {len(matrix.people)} {'person' if len(matrix.people) == 1 else 'people'} "
            f"({active_people_count} active) "
            f"within {len(matrix.clusters)} cluster{'' if len(matrix.clusters) == 1 else 's'} "
            f"for a total of {total_event_count} event{'' if total_event_count == 1 else 's'} (of which {future_event_count} {'is' if future_event_count == 1 else 'are'} in the future)."
        )
        print("\n".join(summary_lines))
        if email := options["save_as"]:
            print(f"Saving data as {email}…")
            with transaction.atomic():
                try:
                    MatrixManager(matrix, use_pre_save=False).ensure_account_and_save(
                        email, "Employee 427", "Hedgebox Inc.", password="12345678", disallow_collision=True
                    )
                except (exceptions.ValidationError, exceptions.PermissionDenied) as e:
                    print(str(e))
            print(f"{email} is ready!")
