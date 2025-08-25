# ruff: noqa: T201 allow print statements

import os

from django.core.management.base import BaseCommand
from django.db import connection


def load_sql(filename):
    path = os.path.join(os.path.dirname(__file__), "../sql/", filename)
    with open(path, encoding="utf_8") as f:
        return f.read()


class Command(BaseCommand):
    help = "Migrate data to new model"

    def add_arguments(self, parser):
        parser.add_argument("--element", default=[], dest="element", action="append")
        parser.add_argument("--reverse", action="store_true", help="unpartition event table")

    def handle(self, *args, **options):
        if options["reverse"]:
            print("Reversing partitions...")
            with connection.cursor() as cursor:
                cursor.execute(load_sql("0050_event_partitions_reverse.sql"))
            return

        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT exists(SELECT FROM information_schema.tables where table_name = \'posthog_event_default\')"""
            )
            exists = cursor.fetchone()
            if exists[0]:
                print("The event table has already been partitioned!")
                return

        elements = []
        if options["element"]:
            elements = options["element"]

        if connection.cursor().connection.server_version >= 120000:
            with connection.cursor() as cursor:
                print("Partitioning...")
                cursor.execute(load_sql("0050_event_partitions.sql"))
                cursor.execute(
                    """DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = \'create_partitions\')) THEN PERFORM create_partitions(%s); END IF; END $$""",
                    [elements],
                )
        else:
            raise Exception("Postgres must be version 12 or greater to apply this partitioning")
