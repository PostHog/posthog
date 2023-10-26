import datetime as dt
import logging
import secrets
from time import monotonic

from django.core import exceptions
from django.core.management.base import BaseCommand

from posthog.demo.matrix import Matrix, MatrixManager
from posthog.demo.products.hedgebox import HedgeboxMatrix
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import Team

logging.getLogger("kafka").setLevel(logging.ERROR)  # Hide kafka-python's logspam


class Command(BaseCommand):
    help = "Generate demo data using the Matrix"

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")
        parser.add_argument(
            "--now",
            type=dt.datetime.fromisoformat,
            help="Simulation 'now' datetime in ISO format (default: now)",
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
        parser.add_argument(
            "--n-clusters",
            type=int,
            default=500,
            help="Number of clusters (default: 500)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Don't save simulation results")
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="If specified, an existing project with this ID will be used, and no new user will be created. If the ID is 0, data will be generated for the master project (but insights etc. won't be created)",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="test@posthog.com",
            help="Email of the demo user (default: test@posthog.com)",
        )
        parser.add_argument(
            "--password",
            type=str,
            default="12345678",
            help="Password of the demo user (default: 12345678)",
        )

    def handle(self, *args, **options):
        timer = monotonic()
        seed = options.get("seed") or secrets.token_hex(16)
        now = options.get("now") or dt.datetime.now(dt.timezone.utc)
        existing_team_id = options.get("team_id")
        if (
            existing_team_id is not None
            and existing_team_id != 0
            and not Team.objects.filter(pk=existing_team_id).exists()
        ):
            print(f"Team with ID {options['team_id']} does not exist!")
            return
        print("Instantiating the Matrix...")
        matrix = HedgeboxMatrix(
            seed,
            now=now,
            days_past=options["days_past"],
            days_future=options["days_future"],
            n_clusters=options["n_clusters"],
            group_type_index_offset=GroupTypeMapping.objects.filter(team_id=existing_team_id).count()
            if existing_team_id
            else 0,
        )
        print("Running simulation...")
        matrix.simulate()
        self.print_results(
            matrix,
            seed=seed,
            duration=monotonic() - timer,
            verbosity=options["verbosity"],
        )
        if not options["dry_run"]:
            email = options["email"]
            password = options["password"]
            matrix_manager = MatrixManager(matrix, print_steps=True)
            try:
                if existing_team_id is not None:
                    if existing_team_id == 0:
                        matrix_manager.reset_master()
                    else:
                        team = Team.objects.get(pk=existing_team_id)
                        existing_user = team.organization.members.first()
                        matrix_manager.run_on_team(team, existing_user)
                else:
                    matrix_manager.ensure_account_and_save(
                        email,
                        "Employee 427",
                        "Hedgebox Inc.",
                        password=password,
                        disallow_collision=True,
                    )
            except exceptions.ValidationError as e:
                print(f"Error: {e}")
            else:
                print(
                    "\nMaster project reset!\n"
                    if existing_team_id == 0
                    else f"\nDemo data ready for project {team.name}!\n"
                    if existing_team_id is not None
                    else f"\nDemo data ready for {email}!\n\n"
                    "Pre-fill the login form with this link:\n"
                    f"http://localhost:8000/login?email={email}\n"
                    f"The password is {password}.\n\n"
                    "If running demo mode (DEMO=1), log in instantly with this link:\n"
                    f"http://localhost:8000/signup?email={email}\n"
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
                f"    Cluster {cluster.index}: {cluster}. Radius = {cluster.radius}. Population = {len(cluster.people_matrix) * len(cluster.people_matrix[0])}."
            )
            for y, person_row in enumerate(cluster.people_matrix):
                for x, person in enumerate(person_row):
                    if verbosity >= 2:
                        summary_lines.append(f"        Person {x, y}: {person}")
                    total_event_count += len(person.past_events) + len(person.future_events)
                    future_event_count += len(person.future_events)
                    if person.all_events:
                        active_people_count += 1
                    if verbosity >= 3:
                        active_session_id = None
                        for event in person.all_events:
                            if session_id := event.properties.get("$session_id"):
                                if active_session_id != session_id:
                                    summary_lines.append(f"            Session {session_id}:")
                                active_session_id = session_id
                            summary_lines.append(f"            {event}")
                    elif verbosity >= 2:
                        event_count = len(person.past_events) + len(person.future_events)
                        if not event_count:
                            summary_lines.append("            No events")
                        else:
                            assert person.first_seen_at is not None and person.last_seen_at is not None
                            session_count = len(set(event.properties.get("$session_id") for event in person.all_events))
                            summary_lines.append(
                                f"            {event_count} event{'' if event_count == 1 else 's'} "
                                f"across {session_count} session{'' if session_count == 1 else 's'} "
                                f"between {person.first_seen_at.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"and {person.last_seen_at.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
        summary_lines.append(
            f"All in all, in {duration * 1000:.2f} ms "
            f"simulated {len(matrix.people)} {'person' if len(matrix.people) == 1 else 'people'} "
            f"({active_people_count} active) "
            f"within {len(matrix.clusters)} cluster{'' if len(matrix.clusters) == 1 else 's'} "
            f"for a total of {total_event_count} event{'' if total_event_count == 1 else 's'} (of which {future_event_count} {'is' if future_event_count == 1 else 'are'} in the future)."
        )
        print("\n".join(summary_lines))
