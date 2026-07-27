# ruff: noqa: T201 allow print statements
"""Render the SQL operations of one or more ClickHouse migrations.

Unlike ``migrate_clickhouse --plan --print-sql``, this command does not connect
to ClickHouse. It imports the requested migration modules, walks their
``operations`` list and prints every ``op._sql`` (the string ``run_sql_with_exceptions``
attaches). It is the basis for the CI step that prints the SQL each migration
will execute under each ``CLOUD_DEPLOYMENT`` value (cloud-gated migrations build
different ``operations`` lists at import time).

With ``--format markdown`` it instead emits a nested markdown list
(environment -> node type(s) -> migration -> SQL) suitable for posting as a PR comment.
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
        parser.add_argument(
            "--format",
            choices=["text", "markdown"],
            default="text",
            help="Output format. 'text' (default) for plain log output; 'markdown' for a nested PR-comment list.",
        )

    def handle(self, *args, **options):
        # Under TEST/E2E settings the MergeTree engine helper appends a random UUID to each
        # ReplicatedMergeTree ZooKeeper path (to avoid clashes between test runs). That makes
        # the rendered SQL non-deterministic across environments, breaking per-env comparison
        # and hiding real divergence. Render production-deterministic ZK paths instead — the
        # engine reads these flags off django.conf.settings at SQL-build time, so flip them
        # before importing the migration modules below.
        settings.TEST = False
        settings.E2E_TESTING = False

        names = [self._normalize(name) for name in options["migrations"]]
        if options["format"] == "markdown":
            self._handle_markdown(names)
        else:
            self._handle_text(names)

    def _handle_text(self, names: list[str]) -> None:
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

    def _handle_markdown(self, names: list[str]) -> None:
        # Emit only the node type(s) -> SQL list, without an environment header. The
        # CI step renders this once per CLOUD_DEPLOYMENT and adds the environment level
        # itself, collapsing it when environments render identically. We don't nest by
        # migration: CI enforces one migration file per PR, and if several are passed
        # their operations are merged by node role (first-seen order preserved).
        groups: dict[str, list[str]] = {}
        notes: list[str] = []
        for name in names:
            module = importlib.import_module(f"{MIGRATIONS_PACKAGE_NAME}.{name}")
            operations = getattr(module, "operations", None)
            if operations is None:
                notes.append(f"`{name}` — no `operations` attribute")
                continue
            if not operations:
                notes.append(f"`{name}` — operations list is empty under this environment")
                continue
            for op in operations:
                sql = getattr(op, "_sql", None)
                if sql is None:
                    continue
                groups.setdefault(self._node_role_label(op), []).append(sql)

        if not groups and not notes:
            print("- _no SQL operations under this environment_")
        for note in notes:
            print(f"- {note}")
        for label, sqls in groups.items():
            print(f"- **{label}**")
            for sql in sqls:
                print("  ```sql")
                print(indent(sql.strip(), "  "))
                print("  ```")

    @staticmethod
    def _node_role_label(op) -> str:
        roles = getattr(op, "_effective_node_roles", None) or getattr(op, "_node_roles", None)
        if not roles:
            return "data (default)"
        return ", ".join(sorted(getattr(role, "value", str(role)) for role in roles))

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
