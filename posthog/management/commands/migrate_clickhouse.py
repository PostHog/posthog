from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.managed_schema import ClickHouseDatabase
from posthog.run_mode import run_mode


class Command(BaseCommand):
    help = "Create or update the ClickHouse schema of a single-cluster install, and load its reference data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exits with a non-zero status if the database differs from the declared schema.",
        )
        parser.add_argument(
            "--plan",
            action="store_true",
            help="Shows the changes that would bring the database to the declared schema.",
        )

    def handle(self, *args, **options):
        if run_mode().is_deployed_cloud:
            # Cloud clusters get their schema from the infrastructure repository, which maps it onto the nodes.
            # Deploy hooks still call this command, so it succeeds without doing anything.
            self.stdout.write("Skipping: the ClickHouse schema of this deployment is not applied by the app")
            return

        database = ClickHouseDatabase()
        if options["check"] or options["plan"]:
            has_changes, plan = database.plan_schema(kafka=True)
            self.stdout.write(plan)
            if has_changes and options["check"]:
                raise CommandError("The ClickHouse schema is not up to date")
            return

        database.create()
        database.apply_schema(kafka=True)
        database.seed()
        self.stdout.write(self.style.SUCCESS("ClickHouse schema is up to date"))
