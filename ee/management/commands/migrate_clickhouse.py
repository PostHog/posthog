from django.core.management.base import BaseCommand
from infi.clickhouse_orm import Database


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def handle(self, *args, **options):
        Database("default").migrate("ee.clickhouse.migrations")
