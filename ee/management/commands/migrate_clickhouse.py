from django.core.management.base import BaseCommand
from django_clickhouse.migrations import migrate_app


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def handle(self, *args, **options):
        migrate_app("ee", "default")
