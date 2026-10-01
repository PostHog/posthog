from django.core.management.base import BaseCommand

from posthog.clickhouse.managed_schema import ClickHouseDatabase
from posthog.run_mode import run_mode


class Command(BaseCommand):
    help = "Create or update the ClickHouse schema of a single-cluster install, and load its reference data"

    def handle(self, *args, **options):
        if run_mode().is_deployed_cloud:
            # Cloud clusters get their schema from the infrastructure repository, which maps it onto the nodes.
            self.stdout.write("Skipping: the ClickHouse schema of this deployment is not applied by the app")
            return

        database = ClickHouseDatabase()
        database.create()
        database.apply_schema(kafka=True)
        database.seed()
        self.stdout.write(self.style.SUCCESS("ClickHouse schema is up to date"))
