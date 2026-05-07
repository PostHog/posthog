# ruff: noqa: T201
"""Write rendered SQL for ClickHouse migrations to posthog/clickhouse/migrations/sql/ as a permanent log.

Each migration gets one subdirectory per environment, containing one .sql file per node type:

    sql/<migration_name>/<env>/<nodetype>.sql

Run via the companion shell script to cover all four environments at once:

    bin/dump-ch-migration-sql

Or run directly for a single environment (CLOUD_DEPLOYMENT must be set in the shell):

    CLOUD_DEPLOYMENT=US python manage.py dump_ch_migration_sql --env us
    CLOUD_DEPLOYMENT=EU python manage.py dump_ch_migration_sql --env eu

Because CLOUD_DEPLOYMENT is read by migration modules at import time, each environment
requires a separate process invocation — the shell script handles this automatically.
"""

import importlib
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

MIGRATIONS_PACKAGE = "posthog.clickhouse.migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "clickhouse" / "migrations"
SQL_DIR = MIGRATIONS_DIR / "sql"
PROJECT_ROOT = MIGRATIONS_DIR.parent.parent.parent


class Command(BaseCommand):
    help = (
        "Write rendered SQL for ClickHouse migrations to "
        "posthog/clickhouse/migrations/sql/<migration>/<env>/<nodetype>.sql. "
        "Run bin/dump-ch-migration-sql to cover all environments at once."
    )
    requires_migrations_checks = False
    requires_system_checks: list[str] = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--env",
            required=True,
            help="Environment directory label (e.g. hobby, us, eu, dev).",
        )
        parser.add_argument(
            "migrations",
            nargs="*",
            help=("Migration names or file paths to process. Defaults to all numbered migration files."),
        )

    def handle(self, *args, **options) -> None:
        env = options["env"].strip().lower()
        if not env:
            raise CommandError("--env must not be empty")

        if options["migrations"]:
            names = [self._normalize(n) for n in options["migrations"]]
        else:
            names = self._discover_all()

        wrote = 0
        for name in names:
            try:
                module = importlib.import_module(f"{MIGRATIONS_PACKAGE}.{name}")
            except Exception as exc:
                self.stderr.write(f"skip {name}: {exc}")
                continue

            operations = getattr(module, "operations", None)
            if not operations:
                continue

            by_nodetype: defaultdict[str, list[str]] = defaultdict(list)
            for op in operations:
                sql: str | None = getattr(op, "_sql", None)
                if sql is None:
                    continue
                node_roles: list = getattr(op, "_node_roles", None) or []
                nodetype = "_".join(str(r) for r in node_roles) if node_roles else "data"
                by_nodetype[nodetype].append(sql.strip())

            for nodetype, sqls in sorted(by_nodetype.items()):
                out_path = SQL_DIR / name / env / f"{nodetype}.sql"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("\n\n".join(sqls) + "\n")
                print(f"  wrote {out_path.relative_to(PROJECT_ROOT)}")
                wrote += 1

        print(f"[env={env}] wrote {wrote} file(s) from {len(names)} migration(s)")

    @staticmethod
    def _discover_all() -> list[str]:
        return [p.stem for p in sorted(MIGRATIONS_DIR.glob("[0-9]*.py"))]

    @staticmethod
    def _normalize(value: str) -> str:
        cleaned = value.strip()
        if cleaned.endswith(".py"):
            cleaned = cleaned[:-3]
        if "/" in cleaned:
            cleaned = cleaned.rsplit("/", 1)[-1]
        if not cleaned:
            raise CommandError("empty migration name")
        return cleaned
