# ruff: noqa: T201 allow print statements

import sys
import logging
import secrets
import argparse
import datetime as dt
from time import monotonic
from typing import Optional
from urllib.parse import quote

from django.core import exceptions
from django.core.management.base import BaseCommand

from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.demo.dashboard_template_seeds import seed_dev_dashboard_templates
from posthog.demo.matrix import Matrix, MatrixManager
from posthog.demo.products.hedgebox import HedgeboxMatrix
from posthog.demo.products.spikegpt import SpikeGPTMatrix
from posthog.management.commands.sync_feature_flags_from_api import sync_feature_flags_from_api
from posthog.models import User
from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.team.setup_tasks import SetupTaskId
from posthog.models.team.team import Team
from posthog.products import Products
from posthog.taxonomy.taxonomy import PERSON_PROPERTIES_ADAPTED_FROM_EVENT

from ee.clickhouse.materialized_columns.analyze import materialize_properties_task

logging.getLogger("kafka").setLevel(logging.ERROR)  # Hide kafka-python's logspam


class Command(BaseCommand):
    help = "Generate demo data using the Matrix"

    # Vetted parameter sets so the fast path is discoverable instead of living only in CI YAML.
    # An explicitly-passed flag always overrides the profile; no profile reproduces the historical defaults.
    DEFAULTS: dict[str, object] = {
        "n_clusters": 500,
        "days_past": 120,
        "days_future": 30,
        "skip_materialization": False,
        "skip_flag_sync": False,
        "skip_user_product_list": False,
    }
    PROFILES: dict[str, dict[str, object]] = {
        # Tiny and fast, matching the MCP CI job — for "just give me some data".
        "smoke": {
            "n_clusters": 10,
            "days_past": 7,
            "days_future": 0,
            "skip_materialization": True,
            "skip_flag_sync": True,
            "skip_user_product_list": True,
        },
        # A complete-but-quick project to click around in.
        "small": {
            "n_clusters": 100,
            "days_past": 30,
            "days_future": 7,
            "skip_materialization": True,
            "skip_flag_sync": True,
            "skip_user_product_list": False,
        },
        # The historical default (everything on).
        "full": dict(DEFAULTS),
    }

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")
        parser.add_argument(
            "--profile",
            type=str,
            choices=sorted(self.PROFILES),
            default=None,
            help="Preset parameter bundle (smoke=tiny/fast, small=quick, full=historical default). "
            "Explicit flags override the profile.",
        )
        parser.add_argument(
            "--now",
            type=dt.datetime.fromisoformat,
            help="Simulation 'now' datetime in ISO format (default: now)",
        )
        parser.add_argument(
            "--days-past",
            type=int,
            default=None,
            help="At how many days before 'now' should the simulation start (default: 120)",
        )
        parser.add_argument(
            "--days-future",
            type=int,
            default=None,
            help="At how many days after 'now' should the simulation end (default: 30)",
        )
        parser.add_argument(
            "--n-clusters",
            type=int,
            default=None,
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
        parser.add_argument(
            "--product",
            type=str,
            default="hedgebox",
            help="Product to simulate (default: hedgebox, alternatives: spikegpt)",
        )
        parser.add_argument(
            "--staff",
            action="store_true",
            default=True,
            help="Whether the demo user should be a staff user (default: True)",
        )
        parser.add_argument(
            "--skip-materialization",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Skip materializing common columns after data generation",
        )
        parser.add_argument(
            "--skip-flag-sync",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Skip syncing feature flags from API after data generation",
        )
        parser.add_argument(
            "--skip-user-product-list",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Skip creating UserProductList entries after data generation",
        )
        parser.add_argument(
            "--say-on-complete",
            action="store_true",
            default=sys.platform == "darwin",
            help="Use text-to-speech to say when the process is complete",
        )

    def handle(self, *args, **options):
        timer = monotonic()
        seed = options.get("seed") or secrets.token_hex(16)
        now = options.get("now") or dt.datetime.now(dt.UTC)
        existing_team_id = options.get("team_id")
        existing_team: Optional[Team] = None

        if existing_team_id is not None and existing_team_id != 0:
            try:
                existing_team = Team.objects.get(pk=existing_team_id)
            except Team.DoesNotExist:
                print(f"Team with ID {options['team_id']} does not exist!")
                return

        profile_config = self.PROFILES.get(options.get("profile") or "", {})

        def resolve(key: str):
            explicit = options.get(key)
            if explicit is not None:
                return explicit
            return profile_config.get(key, self.DEFAULTS[key])

        n_clusters = resolve("n_clusters")
        days_past = resolve("days_past")
        days_future = resolve("days_future")
        skip_materialization = resolve("skip_materialization")
        skip_flag_sync = resolve("skip_flag_sync")
        skip_user_product_list = resolve("skip_user_product_list")
        if options.get("profile"):
            print(
                f"Using '{options['profile']}' profile: n_clusters={n_clusters}, days_past={days_past}, "
                f"days_future={days_future}, skip_materialization={skip_materialization}, "
                f"skip_flag_sync={skip_flag_sync}, skip_user_product_list={skip_user_product_list}."
            )

        print("Instantiating the Matrix...")
        try:
            RelevantMatrix = {"hedgebox": HedgeboxMatrix, "spikegpt": SpikeGPTMatrix}[options["product"]]
        except KeyError:
            print(f"Error: Product {options['product']} is not supported!")
            return
        matrix = RelevantMatrix(
            seed,
            now=now,
            days_past=days_past,
            days_future=days_future,
            n_clusters=n_clusters,
            group_type_index_offset=(
                len(get_group_types_for_project(existing_team.project_id)) if existing_team else 0
            ),
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
            team: Optional[Team] = None
            user = None

            try:
                if existing_team_id is not None:
                    if existing_team_id == 0:
                        matrix_manager.reset_master()
                    else:
                        team = Team.objects.get(pk=existing_team_id)
                        user = team.organization.members.first()
                        if user is None:
                            raise ValueError(f"Project {existing_team_id} has no organization members")
                        matrix_manager.run_on_team(team, user)
                else:
                    _organization, team, user = matrix_manager.ensure_account_and_save(
                        email,
                        "Employee 427",
                        "Hedgebox Inc.",
                        is_staff=bool(options.get("staff")),
                        password=password,
                        email_collision_handling="disambiguate",
                    )

                    # Optionally generate demo issues for issue tracker if extension is available
                    gen_issues = getattr(self, "generate_demo_issues", None)
                    team_for_issues = getattr(matrix_manager, "team", None)
                    if callable(gen_issues) and team_for_issues is not None:
                        gen_issues(team_for_issues)
            except exceptions.ValidationError as e:
                print(f"Error: {e}")

            if not skip_materialization:
                print("Materializing common columns...")
                self.materialize_common_columns(days_past)
            else:
                print("Skipping materialization of common columns.")

            if not skip_flag_sync:
                print("Syncing feature flags from API...")
                try:
                    sync_feature_flags_from_api(distinct_id="generate_demo_data", output_fn=self.stdout.write)
                except Exception as e:
                    print(f"Feature flag sync failed: {e}")
                    print("Continuing anyway...")
            else:
                print("Skipping feature flag sync.")

            if not skip_user_product_list:
                # Create UserProductList entries for all products
                # Skip if existing_team_id == 0 (master project reset)
                if existing_team_id != 0 and team and user:
                    print("Creating UserProductList entries for all products...")
                    self.create_default_user_product_list(team, user)
            else:
                print("Skipping UserProductList creation.")

            if existing_team_id != 0 and team:
                print("Marking all quick start tasks as completed...")
                self.complete_all_quick_start_tasks(team)

            print("Seeding extra global dashboard templates (dev)...")
            created_templates = seed_dev_dashboard_templates()
            if created_templates:
                print(f"Created dashboard templates: {', '.join(created_templates)}")
            else:
                print("Dashboard template seeds already present.")

            print(
                "\nMaster project reset!\n"
                if existing_team_id == 0
                else (
                    f"\nDemo data ready for project {(team.name if team is not None else 'unknown project')}!\n"
                    if existing_team_id is not None
                    else f"\nDemo data ready for {(user.email if user is not None else 'unknown user')}!\n\n"
                    "Pre-fill the login form with this link:\n"
                    f"http://localhost:8010/login?email={quote(user.email if user is not None else '')}\n"
                    f"The password is:\n{password}\n\n"
                    "If running demo mode (DEMO=1), log in instantly with this link:\n"
                    f"http://localhost:8010/signup?email={quote(user.email if user is not None else '')}\n"
                )
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
                            session_count = len({event.properties.get("$session_id") for event in person.all_events})
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

    def materialize_common_columns(self, backfill_days: int) -> None:
        event_properties = {
            *PERSON_PROPERTIES_ADAPTED_FROM_EVENT,
            "$prev_pageview_pathname",
            "$prev_pageview_max_content_percentage",
            "$prev_pageview_max_scroll_percentage",
            "$screen_name",
            "$lib",
            "$lib_version",
            "$geoip_country_code",
            "$geoip_subdivision_1_code",
            "$geoip_subdivision_1_name",
            "$geoip_city_name",
            "$browser_language",
            "$timezone_offset",
            "$host",
            "$exception_issue_id",
            "$exception_types",
            "$exception_values",
            "$exception_sources",
            "$exception_functions",
            "$exception_fingerprint",
        }

        person_properties = {
            *PERSON_PROPERTIES_ADAPTED_FROM_EVENT,
            *PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES,
        }
        for prop in person_properties.copy():
            if prop.startswith("$initial_"):
                continue
            person_properties.add("$initial_" + (prop[1:] if prop[0] == "$" else prop))

        materialize_properties_task(
            properties_to_materialize=[
                (
                    "events",
                    "properties",
                    prop,
                )
                for prop in sorted(event_properties)
            ],
            backfill_period_days=backfill_days,
        )
        materialize_properties_task(
            properties_to_materialize=[
                (
                    "events",
                    "person_properties",
                    prop,
                )
                for prop in sorted(person_properties)
            ],
            backfill_period_days=backfill_days,
        )
        materialize_properties_task(
            properties_to_materialize=[
                (
                    "person",
                    "properties",
                    prop,
                )
                for prop in sorted(person_properties)
            ],
            backfill_period_days=backfill_days,
        )

    def create_default_user_product_list(self, team: Team, user: User) -> None:
        """Create UserProductList entries for all default sidebar products."""
        product_paths = Products.get_product_paths()
        created_count = 0
        for product_path in product_paths:
            _, created = UserProductList.objects.get_or_create(
                team=team,
                user=user,
                product_path=product_path,
                defaults={
                    "enabled": True,
                    "reason": None,
                },
            )
            if created:
                created_count += 1
        print(f"Created {created_count} UserProductList entries for {len(product_paths)} products.")

    @staticmethod
    def complete_all_quick_start_tasks(team: Team) -> None:
        """Mark all quick start tasks as completed so the setup UI doesn't show."""
        team.onboarding_tasks = dict.fromkeys(SetupTaskId, "completed")
        team.save(update_fields=["onboarding_tasks"])
        print(f"Marked {len(SetupTaskId)} quick start tasks as completed.")
