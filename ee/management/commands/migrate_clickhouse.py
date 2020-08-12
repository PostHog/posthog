from django.core.management.base import BaseCommand
from django_clickhouse.migrations import migrate_app


class Command(BaseCommand):
    help = "Migrate data to new model"

    def add_arguments(self, parser):
        parser.add_argument("--element", default=[], dest="element", action="append")
        parser.add_argument("--reverse", action="store_true", help="unpartition event table")

    def handle(self, *args, **options):
        migrate_app("ee", "default")
