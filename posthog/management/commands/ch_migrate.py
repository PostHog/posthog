# ruff: noqa: T201 allow print statements
"""
ClickHouse schema management -- declarative, Terraform-style.

Subcommands (10):
  plan       -- diff schema/*.yaml vs live ClickHouse, show plan
  apply      -- execute the diff (plan + apply)
  generate   -- scaffold a new schema YAML from a template
  drift      -- detect per-host schema divergence
  schema     -- dump current live schema
  status     -- show per-host migration state
  bootstrap  -- create the tracking table
  check      -- show pending legacy migrations
  lint       -- lint schema YAML files
  down       -- roll back a legacy migration

Modules: desired_state, state_diff, plan_generator, schema_graph,
schema_introspect, tracking.
"""

import sys
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.clickhouse.cluster import get_all_logical_clusters, get_cluster_by_name, is_known_cluster
from posthog.clickhouse.migration_tools.schema_introspect import detect_drift, dump_schema

MAX_DRIFT_DISPLAY = 10
DEFAULT_SCHEMA_DIR = "posthog/clickhouse/schema"


def _any_client(cluster: Any) -> Any:
    return cluster.any_host(lambda c: c).result()


class Command(BaseCommand):
    help = "ClickHouse schema management -- plan, apply, generate, drift, schema, status, bootstrap, check, lint, down, orphans, version"

    def add_arguments(self, parser: Any) -> None:
        subparsers = parser.add_subparsers(dest="subcommand")

        # plan -- diff desired vs current
        plan_parser = subparsers.add_parser("plan", help="Diff desired-state YAML vs live ClickHouse")
        plan_parser.add_argument(
            "--schema-dir",
            type=str,
            default=DEFAULT_SCHEMA_DIR,
            help="Directory with desired-state YAML files",
        )
        plan_parser.add_argument(
            "--cluster",
            type=str,
            default=None,
            help="Filter to a specific cluster (e.g. main, logs). Default: all clusters.",
        )

        # apply -- execute the diff
        apply_parser = subparsers.add_parser("apply", help="Execute the reconciliation plan")
        apply_parser.add_argument(
            "--schema-dir",
            type=str,
            default=DEFAULT_SCHEMA_DIR,
            help="Directory with desired-state YAML files",
        )
        apply_parser.add_argument("--force", action="store_true", default=False)
        apply_parser.add_argument("--yes", "-y", action="store_true", default=False, help="Skip confirmation prompt")
        apply_parser.add_argument("--cluster", type=str, default=None, help="Filter to a specific cluster")

        # generate -- scaffold schema YAML from template
        gen_parser = subparsers.add_parser("generate", help="Generate a schema YAML file from a template")
        gen_parser.add_argument("--template", type=str, required=True, help="Template name (e.g. ingestion_pipeline)")
        gen_parser.add_argument("--table", type=str, required=True, help="Base table name")
        gen_parser.add_argument("--cluster", type=str, default="main", help="Target cluster (default: main)")
        gen_parser.add_argument(
            "--output-dir",
            type=str,
            default=DEFAULT_SCHEMA_DIR,
            help="Output directory for YAML file",
        )

        # drift
        subparsers.add_parser("drift", help="Detect schema drift between cluster hosts")

        # schema
        subparsers.add_parser("schema", help="Dump current schema state from ClickHouse")

        # status
        status_parser = subparsers.add_parser("status", help="Show per-host migration state")
        status_parser.add_argument("--node", type=str, default=None, help="Filter by hostname")

        # bootstrap
        subparsers.add_parser("bootstrap", help="Create the tracking table on all nodes")

        # check
        subparsers.add_parser("check", help="Show pending legacy migrations")

        # lint
        lint_parser = subparsers.add_parser("lint", help="Lint schema YAML files")
        lint_parser.add_argument(
            "--schema-dir",
            type=str,
            default=DEFAULT_SCHEMA_DIR,
            help="Directory with desired-state YAML files",
        )

        # orphans
        orphans_parser = subparsers.add_parser("orphans", help="List production tables not declared in any YAML")
        orphans_parser.add_argument(
            "--schema-dir",
            type=str,
            default=DEFAULT_SCHEMA_DIR,
            help="Directory with desired-state YAML files",
        )
        orphans_parser.add_argument(
            "--exclude",
            type=str,
            nargs="*",
            default=[],
            help="Additional table names to exclude",
        )

        # version
        subparsers.add_parser("version", help="Show the last applied schema version (git commit)")

        # down (legacy)
        down_parser = subparsers.add_parser("down", help="Roll back a legacy migration by number")
        down_parser.add_argument("migration_number", type=int, help="Migration number to roll back")

    def handle(self, *args: Any, **options: Any) -> None:
        subcommand = options.get("subcommand")
        handlers: dict[str, Any] = {
            "plan": self.handle_plan,
            "apply": self.handle_apply,
            "generate": self.handle_generate,
            "drift": self.handle_drift,
            "schema": self.handle_schema,
            "status": self.handle_status,
            "bootstrap": self.handle_bootstrap,
            "check": self.handle_check,
            "lint": self.handle_lint,
            "orphans": self.handle_orphans,
            "version": self.handle_version,
            "down": self.handle_down,
        }
        handler = handlers.get(subcommand or "")
        if handler:
            handler(options)
        else:
            self.print_help("manage.py", "ch_migrate")

    # ------------------------------------------------------------------
    # plan / apply -- desired-state reconciliation
    # ------------------------------------------------------------------

    def _compute_diffs(
        self, database: str, schema_dir: Any, cluster_filter: str | None = None
    ) -> tuple[list, str | None]:
        """Compute desired-vs-current diffs. Returns (diffs, error_message).

        Connects to the correct ClickHouse host for each logical cluster
        declared in the YAML files. When *cluster_filter* is set, only YAML
        files matching that cluster are diffed.
        """
        from collections import defaultdict

        from posthog.clickhouse.migration_tools.desired_state import parse_desired_state_dir
        from posthog.clickhouse.migration_tools.state_diff import diff_state

        desired_states = parse_desired_state_dir(schema_dir)
        if not desired_states:
            return [], f"No YAML files found in {schema_dir}"

        if cluster_filter:
            desired_states = [ds for ds in desired_states if ds.cluster == cluster_filter]
            if not desired_states:
                return [], f"No YAML files for cluster '{cluster_filter}' in {schema_dir}"

        # Validate cluster names
        for ds in desired_states:
            if not is_known_cluster(ds.cluster):
                known = ", ".join(get_all_logical_clusters())
                return [], (
                    f"Schema file for ecosystem '{ds.ecosystem}' references cluster "
                    f"'{ds.cluster}' which is not in the cluster registry. "
                    f"Known clusters: {known}. "
                    f"Add '{ds.cluster}' to _REGISTRY in posthog/clickhouse/cluster.py with the "
                    f"appropriate CLICKHOUSE_*_HOST and CLICKHOUSE_*_CLUSTER settings."
                )

        # Group desired states by cluster so we connect once per cluster
        by_cluster: dict[str, list] = defaultdict(list)
        for ds in desired_states:
            by_cluster[ds.cluster].append(ds)

        all_diffs = []
        for cluster_name, states in by_cluster.items():
            cluster_obj = get_cluster_by_name(cluster_name)
            client = _any_client(cluster_obj)
            current = dump_schema(client, database)

            for desired in states:
                ecosystem_current = {name: table for name, table in current.items() if name in desired.tables}
                diffs = diff_state(desired, ecosystem_current, database=database)
                all_diffs.extend(diffs)

        return all_diffs, None

    def handle_plan(self, options: dict[str, Any]) -> None:
        from pathlib import Path

        from posthog.clickhouse.migration_tools.plan_generator import generate_plan_text

        database: str = settings.CLICKHOUSE_DATABASE
        schema_dir = Path(options.get("schema_dir", DEFAULT_SCHEMA_DIR))

        if not schema_dir.exists():
            print(f"Schema directory not found: {schema_dir}")
            print("Run 'ch_migrate generate' to create schema YAML files.")
            return

        cluster_filter = options.get("cluster")
        all_diffs, err = self._compute_diffs(database, schema_dir, cluster_filter=cluster_filter)
        if err:
            print(err)
            return

        if cluster_filter:
            print(f"Filtering to cluster: {cluster_filter}\n")
        print(generate_plan_text(all_diffs))

    def handle_apply(self, options: dict[str, Any]) -> None:
        import time
        import socket
        import hashlib
        import subprocess
        from pathlib import Path

        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.plan_generator import generate_manifest_steps, generate_plan_text
        from posthog.clickhouse.migration_tools.runner import execute_migration_step
        from posthog.clickhouse.migration_tools.tracking import (
            StepRecord,
            _record_step,
            acquire_apply_lock,
            record_schema_version,
            release_apply_lock,
        )

        database: str = settings.CLICKHOUSE_DATABASE
        force: bool = options.get("force", False)
        schema_dir = Path(options.get("schema_dir", DEFAULT_SCHEMA_DIR))

        if not schema_dir.exists():
            print(f"Schema directory not found: {schema_dir}")
            return

        cluster_obj = get_migrations_cluster()
        client = _any_client(cluster_obj)
        hostname = socket.gethostname()

        cluster_filter = options.get("cluster")
        all_diffs, err = self._compute_diffs(database, schema_dir, cluster_filter=cluster_filter)
        if err:
            print(err)
            return

        if not all_diffs:
            print("No changes. Infrastructure is up to date.")
            return

        print(generate_plan_text(all_diffs))
        print()

        auto_approve: bool = options.get("yes", False)
        if not auto_approve:
            answer = input(f"Apply {len(all_diffs)} change(s)? [y/N] ")
            if answer.lower() not in ("y", "yes"):
                print("Aborted.")
                return

        acquired, reason = acquire_apply_lock(client, database, hostname, force=force)
        if not acquired:
            print(reason)
            return

        try:
            steps = generate_manifest_steps(all_diffs)
            print(f"Applying {len(steps)} step(s)...\n")

            max_retries = 3
            for i, (step, rendered_sql) in enumerate(steps):
                print(f"  Step {i}: {step.comment}...", end=" ", flush=True)
                checksum = hashlib.sha256(rendered_sql.encode()).hexdigest()
                success = False
                for attempt in range(max_retries):
                    try:
                        execute_migration_step(cluster_obj, step, rendered_sql)
                        success = True
                        break
                    except Exception as exc:
                        if attempt < max_retries - 1:
                            wait = 2**attempt
                            print(f"\n    Retry {attempt + 1}/{max_retries} in {wait}s: {exc}", flush=True)
                            time.sleep(wait)
                        else:
                            print(f"FAILED after {max_retries} attempts: {exc}")
                            _record_step(
                                client=client,
                                record=StepRecord(
                                    migration_number=0,
                                    migration_name=step.comment or "reconcile",
                                    step_index=i,
                                    host=hostname,
                                    node_role="*",
                                    direction="up",
                                    checksum=checksum,
                                    success=False,
                                ),
                                database=database,
                            )
                            print("\nApply halted. Review the error and retry.")
                            return

                if success:
                    print("OK")
                    _record_step(
                        client=client,
                        record=StepRecord(
                            migration_number=0,
                            migration_name=step.comment or "reconcile",
                            step_index=i,
                            host=hostname,
                            node_role="*",
                            direction="up",
                            checksum=checksum,
                            success=True,
                        ),
                        database=database,
                    )
        finally:
            release_apply_lock(client, database, hostname)

        # Record the git commit hash of the schema that was applied
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                record_schema_version(client, database, result.stdout.strip(), hostname)
                print(f"Schema version recorded: {result.stdout.strip()[:12]}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # git not available — skip version recording

        print("\nApply completed successfully.")

    # ------------------------------------------------------------------
    # generate -- scaffold schema YAML from template
    # ------------------------------------------------------------------

    def handle_generate(self, options: dict[str, Any]) -> None:
        from pathlib import Path

        from posthog.clickhouse.migration_tools.templates import generate_schema_yaml

        template_name = options["template"]
        table_name = options["table"]
        cluster_name = options.get("cluster", "main")
        output_dir = Path(options.get("output_dir", DEFAULT_SCHEMA_DIR))

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{table_name}.yaml"

        if output_path.exists():
            print(f"Schema file already exists: {output_path}")
            print("Edit it directly or delete it first.")
            return

        yaml_data = generate_schema_yaml(template_name, table_name, cluster_name)
        if yaml_data is None:
            return

        import yaml as yaml_lib

        with open(output_path, "w") as f:
            yaml_lib.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

        table_count = len(yaml_data.get("tables", {}))
        print(f"Generated: {output_path} ({table_count} table(s))")
        print(f"Edit the YAML, then run: ch_migrate plan")

    # ------------------------------------------------------------------
    # drift
    # ------------------------------------------------------------------

    def handle_drift(self, options: dict[str, Any]) -> None:
        database: str = settings.CLICKHOUSE_DATABASE

        print(f"Checking schema drift across all registered clusters (database={database})...")

        all_diffs = []
        for name in get_all_logical_clusters():
            try:
                cluster = get_cluster_by_name(name)
                diffs = detect_drift(cluster, database)
                if diffs:
                    print(f"\nDrift detected on cluster '{name}':")
                    for diff in diffs:
                        host_label = f" [{diff.host}]" if diff.host else ""
                        if diff.column:
                            print(f"  {diff.diff_type}: {diff.table}.{diff.column}{host_label}")
                        else:
                            print(f"  {diff.diff_type}: {diff.table}{host_label}")
                        if diff.expected:
                            print(f"    expected: {diff.expected}")
                        if diff.actual:
                            print(f"    actual:   {diff.actual}")
                    all_diffs.extend(diffs)
            except Exception as e:
                print(f"  Warning: could not connect to cluster '{name}': {e}")

        if not all_diffs:
            print("No schema drift detected across all clusters.")
            return

        sys.exit(1)

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def handle_schema(self, options: dict[str, Any]) -> None:
        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_cluster_by_name("main")

        client = _any_client(cluster)
        schema = dump_schema(client, database)

        if not schema:
            print("No tables found.")
            return

        print(f"Schema for database '{database}' ({len(schema)} table(s)):\n")
        for table_name in sorted(schema.keys()):
            table = schema[table_name]
            print(f"  {table_name} (engine={table.engine})")
            if table.sorting_key:
                print(f"    ORDER BY {table.sorting_key}")
            if table.partition_key:
                print(f"    PARTITION BY {table.partition_key}")
            for col in table.columns:
                default_str = f" DEFAULT {col.default_expression}" if col.default_expression else ""
                print(f"    - {col.name}: {col.type}{default_str}")
            print()

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def handle_status(self, options: dict[str, Any]) -> None:
        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_cluster_by_name("main")
        client = _any_client(cluster)

        from posthog.clickhouse.migration_tools.tracking import TRACKING_TABLE_NAME, _ensure_tracking_table

        _ensure_tracking_table(client, database)

        node_filter = options.get("node")

        if node_filter:
            import re

            if not re.match(r"^[a-zA-Z0-9._:-]+$", node_filter):
                print(f"Invalid node filter: {node_filter!r}")
                return
            rows = client.execute(
                f"SELECT migration_number, migration_name, host, direction, applied_at, success "
                f"FROM {database}.{TRACKING_TABLE_NAME} "
                f"WHERE migration_number > 0 AND host = %(host)s "
                f"ORDER BY applied_at DESC LIMIT 50",
                {"host": node_filter},
            )
        else:
            rows = client.execute(
                f"SELECT migration_number, migration_name, host, direction, applied_at, success "
                f"FROM {database}.{TRACKING_TABLE_NAME} "
                f"WHERE migration_number > 0 "
                f"ORDER BY applied_at DESC LIMIT 50"
            )

        if not rows:
            print("No migration records found.")
            return

        print(f"Recent migration records (database={database}):\n")
        for number, name, host, direction, applied_at, success in rows:
            status = "OK" if success else "FAILED"
            print(f"  {number:04d} {name:40s} {direction:4s} {host:20s} {applied_at} {status}")

    # ------------------------------------------------------------------
    # bootstrap
    # ------------------------------------------------------------------

    def handle_bootstrap(self, options: dict[str, Any]) -> None:
        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_cluster_by_name("main")
        client = _any_client(cluster)

        from posthog.clickhouse.migration_tools.tracking import _ensure_tracking_table

        _ensure_tracking_table(client, database)
        print(f"Tracking table ensured in database '{database}'.")

    # ------------------------------------------------------------------
    # check -- pending legacy migrations
    # ------------------------------------------------------------------

    def handle_check(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.migration_tools.runner import get_pending_migrations

        pending = get_pending_migrations()
        if not pending:
            print("No pending legacy migrations.")
            return

        print(f"{len(pending)} pending legacy migration(s):\n")
        for m in pending:
            print(f"  {m}")

    # ------------------------------------------------------------------
    # lint -- validate schema YAML files
    # ------------------------------------------------------------------

    def handle_lint(self, options: dict[str, Any]) -> None:
        from pathlib import Path

        from posthog.clickhouse.migration_tools.desired_state import parse_desired_state_dir
        from posthog.clickhouse.migration_tools.validator import validate_desired_states

        schema_dir = Path(options.get("schema_dir", DEFAULT_SCHEMA_DIR))
        if not schema_dir.exists():
            print(f"Schema directory not found: {schema_dir}")
            return

        desired_states = parse_desired_state_dir(schema_dir)
        if not desired_states:
            print(f"No YAML files found in {schema_dir}")
            return

        errors = validate_desired_states(desired_states)
        if not errors:
            print(f"All {len(desired_states)} schema file(s) passed lint.")
            return

        print(f"Lint errors ({len(errors)}):\n")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # orphans -- find undeclared tables
    # ------------------------------------------------------------------

    def handle_orphans(self, options: dict[str, Any]) -> None:
        from pathlib import Path

        from posthog.clickhouse.migration_tools.desired_state import parse_desired_state_dir
        from posthog.clickhouse.migration_tools.schema_introspect import dump_schema
        from posthog.clickhouse.migration_tools.state_diff import detect_orphans

        database: str = settings.CLICKHOUSE_DATABASE
        schema_dir = Path(options.get("schema_dir", DEFAULT_SCHEMA_DIR))

        if not schema_dir.exists():
            print(f"Schema directory not found: {schema_dir}")
            return

        desired_states = parse_desired_state_dir(schema_dir)
        if not desired_states:
            print(f"No YAML files found in {schema_dir}")
            return

        cluster = get_cluster_by_name("main")
        client = _any_client(cluster)
        current = dump_schema(client, database)
        exclude = options.get("exclude") or []

        orphans = detect_orphans(desired_states, current, exclude)

        if not orphans:
            print("No orphan tables found. All production tables are declared in YAML.")
            return

        print(f"Orphan tables ({len(orphans)}) — in production but not declared in any YAML:\n")
        for name in orphans:
            engine = current[name].engine if name in current else "?"
            print(f"  {name} (engine={engine})")
        print("\nThese tables may be leftover from old migrations or manual creation.")

    # ------------------------------------------------------------------
    # version -- show last applied schema version
    # ------------------------------------------------------------------

    def handle_version(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.migration_tools.tracking import _ensure_tracking_table, get_latest_schema_version

        database: str = settings.CLICKHOUSE_DATABASE
        cluster = get_cluster_by_name("main")
        client = _any_client(cluster)

        _ensure_tracking_table(client, database)
        version = get_latest_schema_version(client, database)

        if version is None:
            print("No schema version recorded. Run 'ch_migrate apply' to record one.")
            return

        commit_hash, host, applied_at = version
        print(f"Last applied schema version:")
        print(f"  Commit:     {commit_hash}")
        print(f"  Applied by: {host}")
        print(f"  Applied at: {applied_at}")

    # ------------------------------------------------------------------
    # down -- legacy rollback
    # ------------------------------------------------------------------

    def handle_down(self, options: dict[str, Any]) -> None:
        from posthog.clickhouse.migration_tools.runner import run_migration_down

        migration_number = options["migration_number"]
        print(f"Rolling back migration {migration_number}...")
        run_migration_down(migration_number)
        print("Done.")
