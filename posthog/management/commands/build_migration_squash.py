import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.migrations.loader import MigrationLoader

from posthog.management.migration_squashing.planner import MigrationSquashPlanner
from posthog.management.migration_squashing.policy import BootstrapPolicy

DEFAULT_BOOTSTRAP_POLICY_PATH = Path("posthog/management/migration_squashing/bootstrap_policy.yaml")


class Command(BaseCommand):
    help = "Build a deterministic, state-verified squash migration"

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            default="posthog",
            help="Django app label to squash (defaults to posthog).",
        )
        parser.add_argument(
            "--start",
            help="Inclusive start migration name. Defaults to first migration after latest existing squash.",
        )
        parser.add_argument(
            "--end",
            help="Inclusive end migration name. Defaults to max_migration.txt (or latest non-squashed migration).",
        )
        parser.add_argument(
            "--name-suffix",
            help="Optional deterministic suffix for generated migration name.",
        )
        parser.add_argument(
            "--allow-operation",
            action="append",
            default=[],
            help="Operation type to allow despite default safety blocklist. Can be passed multiple times.",
        )
        parser.add_argument(
            "--json-report",
            help="Optional path to write the full analysis report as JSON.",
        )
        parser.add_argument(
            "--rewrite-concurrent-indexes",
            action="store_true",
            help=(
                "Rewrite index-concurrent operations to bootstrap-safe non-concurrent variants "
                "in the generated squashed migration."
            ),
        )
        parser.add_argument(
            "--bootstrap-policy",
            help=(
                "Optional YAML policy file for resolving blocked operations. "
                "Unresolved entries (missing action) remain blockers."
            ),
        )
        parser.add_argument(
            "--overwrite-existing",
            action="store_true",
            help="When writing, overwrite an existing generated migration file with different content.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            help="Write the generated squash migration. Without this flag the command is dry-run only.",
        )

    def handle(self, *args, **options):
        app_label: str = options["app"]
        allow_operation_types = set(options["allow_operation"])
        bootstrap_policy_arg: str | None = options.get("bootstrap_policy")
        if bootstrap_policy_arg:
            bootstrap_policy_path = Path(bootstrap_policy_arg)
        elif DEFAULT_BOOTSTRAP_POLICY_PATH.exists():
            bootstrap_policy_path = DEFAULT_BOOTSTRAP_POLICY_PATH
        else:
            bootstrap_policy_path = None
        bootstrap_policy = BootstrapPolicy.from_path(bootstrap_policy_path)

        loader = MigrationLoader(None, ignore_no_migrations=True)
        planner = MigrationSquashPlanner(
            loader=loader,
            app_label=app_label,
            allow_operation_types=allow_operation_types,
            bootstrap_policy=bootstrap_policy,
        )

        start_name = options["start"] or planner.infer_default_start()
        end_name = options["end"] or planner.infer_default_end()

        analysis = planner.analyze_span(start_name, end_name, name_suffix=options.get("name_suffix"))
        self._print_analysis(analysis, app_label=app_label)

        json_report = options.get("json_report")
        if json_report:
            report_path = Path(json_report)
            report_path.write_text(json.dumps(analysis.to_json_dict(), indent=2, sort_keys=True) + "\n")
            self.stdout.write(f"Wrote analysis report to {report_path}")

        if not analysis.included_span:
            raise CommandError("No squashable migrations found in the requested span.")

        if not analysis.state_equivalent:
            raise CommandError("State equivalence verification failed. Refusing to generate migration.")

        if options["write"]:
            migration_path = planner.write_migration(
                analysis,
                rewrite_concurrent_indexes=options["rewrite_concurrent_indexes"],
                overwrite_existing=options["overwrite_existing"],
            )
            self.stdout.write(self.style.SUCCESS(f"Wrote squash migration: {migration_path}"))
        else:
            self.stdout.write("")
            self.stdout.write("Dry run only. Re-run with `--write` to create the migration file.")

    def _print_analysis(self, analysis, app_label: str) -> None:
        self.stdout.write("")
        self.stdout.write("Migration squash analysis")
        self.stdout.write(f"  App: {app_label}")
        self.stdout.write(f"  Requested span: {analysis.requested_start} -> {analysis.requested_end}")
        self.stdout.write(f"  Requested migrations: {len(analysis.requested_span)}")

        if analysis.included_span:
            self.stdout.write(
                f"  Squashable span: {analysis.included_start} -> {analysis.included_end} "
                f"({len(analysis.included_span)} migrations)"
            )
        else:
            self.stdout.write("  Squashable span: none")

        self.stdout.write(
            f"  Operations: {analysis.original_operation_count} -> {analysis.optimized_operation_count} after optimize"
        )
        self.stdout.write(f"  State equivalence: {'PASS' if analysis.state_equivalent else 'FAIL'}")
        self.stdout.write(f"  Generated migration name: {analysis.generated_migration_name}")

        if analysis.dependencies:
            self.stdout.write("  Dependencies kept:")
            for app, migration in analysis.dependencies:
                self.stdout.write(f"    - {app}.{migration}")

        if analysis.blockers:
            self.stdout.write("")
            self.stdout.write("Blockers")
            for blocker in analysis.blockers:
                self.stdout.write(
                    f"  - {blocker.migration} #{blocker.operation_index} {blocker.operation_type}: {blocker.reason}"
                )
            blocked_migration = analysis.blockers[0].migration
            blocked_index = analysis.requested_span.index(blocked_migration)
            if blocked_index + 1 < len(analysis.requested_span):
                next_start = analysis.requested_span[blocked_index + 1]
                self.stdout.write(f"  Next incremental span: rerun with `--start {next_start}`")

        if analysis.state_differences:
            self.stdout.write("")
            self.stdout.write("State differences")
            for diff in analysis.state_differences:
                self.stdout.write(f"  - {diff}")
