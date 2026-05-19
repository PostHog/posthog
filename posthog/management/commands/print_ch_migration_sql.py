# ruff: noqa: T201 allow print statements
"""Render the SQL operations of one or more ClickHouse migrations.

Unlike ``migrate_clickhouse --plan --print-sql``, this command does not connect
to ClickHouse. It imports the requested migration modules, walks their
``operations`` list and prints every ``op._sql`` (the string ``run_sql_with_exceptions``
attaches). It is the basis for the CI step that prints the SQL each migration
will execute under each ``CLOUD_DEPLOYMENT`` value (cloud-gated migrations build
different ``operations`` lists at import time).
"""

import importlib
from textwrap import indent

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

MIGRATIONS_PACKAGE_NAME = "posthog.clickhouse.migrations"


class Command(BaseCommand):
    help = (
        "Print rendered SQL for the given ClickHouse migration(s) under the current "
        "CLOUD_DEPLOYMENT. Pass either bare migration names (e.g. 0247_warpstream_shared_kafka_engines) "
        "or full file paths."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "migrations",
            nargs="+",
            help="Migration names or paths (e.g. 0247_foo or posthog/clickhouse/migrations/0247_foo.py).",
        )

    def handle(self, *args, **options):
        names = [self._normalize(name) for name in options["migrations"]]

        print(f"# CLOUD_DEPLOYMENT={settings.CLOUD_DEPLOYMENT!r}")
        for name in names:
            module = importlib.import_module(f"{MIGRATIONS_PACKAGE_NAME}.{name}")
            operations = getattr(module, "operations", None)
            if operations is None:
                print(f"\n## {name}\n  (no `operations` attribute)")
                continue
            print(f"\n## {name}  ({len(operations)} operation(s))")
            if not operations:
                print("  (operations list is empty under this CLOUD_DEPLOYMENT)")
                continue
            for idx, op in enumerate(operations):
                sql = getattr(op, "_sql", None)
                if sql is None:
                    print(f"\n### op #{idx} — {type(op).__name__} (no _sql attribute)")
                    continue
                print(f"\n### op #{idx}")
                print(indent(sql, "    "))

    @staticmethod
    def _normalize(value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise CommandError("empty migration name")
        if cleaned.endswith(".py"):
            cleaned = cleaned[:-3]
        if "/" in cleaned:
            cleaned = cleaned.rsplit("/", 1)[-1]
        return cleaned
