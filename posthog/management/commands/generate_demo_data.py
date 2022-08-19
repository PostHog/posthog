import datetime as dt
import logging
import secrets
from time import monotonic
from typing import cast

from django.core import exceptions
from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo.matrix import Matrix, MatrixManager
from posthog.demo.matrix.models import SimEvent
from posthog.demo.products.hedgebox import HedgeboxMatrix

logging.getLogger("kafka").setLevel(logging.WARNING)  # Hide kafka-python's logspam


class Command(BaseCommand):
    help = "Generate demo data using the Matrix"

    def add_arguments(self, parser):
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
        parser.add_argument("--n-clusters", type=int, default=500, help="Number of clusters (default: 500)")
        parser.add_argument("--dry-run", action="store_true", help="Don't save simulation results")
        parser.add_argument(
            "--reset-master", action="store_true", help="Reset master project instead of creating a demo project"
        )
        parser.add_argument(
            "--email", type=str, default="test@posthog.com", help="Email of the demo user (default: test@posthog.com)",
        )
        parser.add_argument(
            "--password", type=str, default="12345678", help="Password of the demo user (default: 12345678)",
        )

    def handle(self, *args, **options):
        timer = monotonic()
        seed = options.get("seed") or secrets.token_hex(16)
        now = options.get("now") or dt.datetime.now(dt.timezone.utc)
        print("Instantiating the Matrix...")
        matrix = HedgeboxMatrix(
            seed,
            now=now,
            days_past=options["days_past"],
            days_future=options["days_future"],
            n_clusters=options["n_clusters"],
        )
        print("Running simulation...")
        matrix.simulate()
        self.print_results(matrix, seed=seed, duration=monotonic() - timer, verbosity=options["verbosity"])
        if not options["dry_run"]:
            email = options["email"]
            password = options["password"]
            matrix_manager = MatrixManager(matrix)
            with transaction.atomic():
                try:
                    if options["reset_master"]:
                        matrix_manager.reset_master()
                    else:
                        matrix_manager.ensure_account_and_save(
                            email,
                            "Employee 427",
                            "Hedgebox Inc.",
                            password=password,
                            disallow_collision=True,
                            print_steps=True,
                        )
                except exceptions.ValidationError as e:
                    print(f"Error: {e}")
                else:
                    print(
                        "Master project reset!"
                        if options["reset_master"]
                        else f"Demo data ready! Log in as {email} with password {password}.\n"
                        "If running DEMO mode locally, log in instantly with this link:\n"
                        f"http://localhost:8000/signup?email={email}"
                    )
        else:
            print("Dry run - not saving results.")

    @staticmethod
    def print_results(matrix: Matrix, *, seed: str, duration: float, verbosity: int):
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
                    if verbosity >= 2:
                        summary_lines.append(f"        Person {x, y}: {person}",)
                    total_event_count += len(person.past_events) + len(person.future_events)
                    future_event_count += len(person.future_events)
                    if person.all_events:
                        active_people_count += 1
                    if verbosity >= 3:
                        active_session_id = None
                        for event in person.all_events:
                            if session_id := event.properties.get("$session_id"):
                                if active_session_id != session_id:
                                    summary_lines.append(f"            Session {session_id}:",)
                                active_session_id = session_id
                            summary_lines.append(f"            {event}",)
                    elif verbosity >= 2:
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
