# based of 0007_persons_and_groups_on_events_backfill.py
# because we can't easily import sth that starts with a number :(
import importlib

import structlog
from django.core.management.base import BaseCommand

from posthog.async_migrations.definition import AsyncMigrationOperation

mig_0007_module = importlib.import_module(
    "posthog.async_migrations.migrations.0007_persons_and_groups_on_events_backfill"
)

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Resync persons on events for a single team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to resync data for.")
        parser.add_argument("--live-run", action="store_true", help="Run all the steps")
        parser.add_argument("--clear-tmp-tables", action="store_true", help="Run clear temporary tables step")
        parser.add_argument("--create-tmp-tables", action="store_true", help="Run create temporary tables step")
        parser.add_argument("--create-dictionaries", action="store_true", help="Run create dictionaries step")
        parser.add_argument("--alter", action="store_true", help="Run alter table update for team-id step")

    def handle(self, *args, **options):
        run_resync(options)


def run_resync(options):
    run_all_steps = options["live_run"]
    if not options["team_id"] and (options["alter"] or run_all_steps):
        logger.error("You must specify --team-id to run this script")
        exit(1)

    TEAM_ID = options["team_id"]
    QUERY_ID = f"resync_persons_on_events:{TEAM_ID}"

    # override to avoid instance lookup in get_parameter function
    class AsyncMig0007(mig_0007_module.Migration):
        def get_parameter(self, name):
            if name == "TEAM_ID":
                return TEAM_ID
            return self.parameters[name][0]

    mig_0007 = AsyncMig0007(QUERY_ID)

    def run_async_migration_op(name, op: AsyncMigrationOperation):
        logger.info(f"Running step {name}")
        op.fn(QUERY_ID)

    def clear_tmp_tables():
        logger.info("Clearing temporary tables")
        mig_0007._clear_temporary_tables(QUERY_ID)

    # start
    if run_all_steps or options["clear_tmp_tables"]:
        clear_tmp_tables()
    if run_all_steps or options["create_tmp_tables"]:
        prep_steps = mig_0007.get_tmp_table_creation_ops()
        for id, step in enumerate(prep_steps):
            run_async_migration_op(f"create temporary tables {id}/{len(prep_steps)}", step)
    if run_all_steps or options["create_dictionaries"]:
        logger.info("Creating dictionaries")
        mig_0007._create_dictionaries(QUERY_ID)
    if run_all_steps or options["alter"]:
        mig_0007._run_backfill_mutation(QUERY_ID)
        mig_0007._wait_for_mutation_done(QUERY_ID)
    if run_all_steps:
        clear_tmp_tables()
