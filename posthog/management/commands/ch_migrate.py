# ruff: noqa: T201 allow print statements
"""
ClickHouse schema management -- declarative, Terraform-style.

Subcommands (this slice):
  plan   -- diff schema/*.yaml vs live ClickHouse, show plan
  apply  -- execute the reconciliation plan

Modules: desired_state, state_diff, plan_generator, runner, tracking,
schema_introspect.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.cluster import get_all_logical_clusters, get_cluster_by_name, is_known_cluster

DEFAULT_SCHEMA_DIR = "posthog/clickhouse/schema"


def _any_client(cluster: Any) -> Any:
    return cluster.any_host(lambda c: c).result()


class Command(BaseCommand):
    help = "ClickHouse schema management -- plan, apply"

    def add_arguments(self, parser: Any) -> None:
        subparsers = parser.add_subparsers(dest="subcommand")

        plan_parser = subparsers.add_parser("plan", help="Diff desired-state YAML vs live ClickHouse")
        plan_parser.add_argument("--schema-dir", type=str, default=DEFAULT_SCHEMA_DIR)
        plan_parser.add_argument("--cluster", type=str, default=None)

        apply_parser = subparsers.add_parser("apply", help="Execute the reconciliation plan")
        apply_parser.add_argument("--schema-dir", type=str, default=DEFAULT_SCHEMA_DIR)
        apply_parser.add_argument("--force", action="store_true", default=False)
        apply_parser.add_argument("--yes", "-y", action="store_true", default=False, help="Skip confirmation prompt")
        apply_parser.add_argument("--cluster", type=str, default=None)
        apply_parser.add_argument(
            "--continue-on-error",
            action="store_true",
            default=False,
            help="Continue applying remaining steps after a failure instead of halting.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        subcommand = options.get("subcommand")
        handlers: dict[str, Any] = {
            "plan": self.handle_plan,
            "apply": self.handle_apply,
        }
        handler = handlers.get(subcommand or "")
        if handler:
            handler(options)
        else:
            self.print_help("manage.py", "ch_migrate")

    def _compute_diffs(
        self, database: str, schema_dir: Any, cluster_filter: str | None = None
    ) -> tuple[list, str | None]:
        """Compute desired-vs-current diffs. Returns (diffs, error_message)."""
        from collections import defaultdict

        from posthog.clickhouse.migration_tools.desired_state import parse_desired_state_dir
        from posthog.clickhouse.migration_tools.state_diff import (
            TRACKING_TABLES,
            StateDiff,
            _drop_stmt,
            diff_state,
            has_placeholder_select,
        )

        desired_states = parse_desired_state_dir(schema_dir)
        if not desired_states:
            return [], f"No YAML files found in {schema_dir}"

        if cluster_filter:
            desired_states = [ds for ds in desired_states if ds.cluster == cluster_filter]
            if not desired_states:
                return [], f"No YAML files for cluster '{cluster_filter}' in {schema_dir}"

        for ds in desired_states:
            if not is_known_cluster(ds.cluster):
                known = ", ".join(get_all_logical_clusters())
                return [], (
                    f"Schema file for ecosystem '{ds.ecosystem}' references cluster "
                    f"'{ds.cluster}' which is not in the cluster registry. "
                    f"Known clusters: {known}."
                )

        by_cluster: dict[str, list] = defaultdict(list)
        for ds in desired_states:
            by_cluster[ds.cluster].append(ds)

        all_desired_names: set[str] = set()
        all_placeholder_names: set[str] = set()
        for ds in desired_states:
            for name, t in ds.tables.items():
                all_desired_names.add(name)
                if has_placeholder_select(t):
                    all_placeholder_names.add(name)

        from posthog.clickhouse.client.migration_tools import get_migrations_cluster
        from posthog.clickhouse.migration_tools.schema_introspect import dump_schema_all_hosts

        def _union_from_cluster(cluster_obj: Any) -> dict[str, Any]:
            per_host = dump_schema_all_hosts(cluster_obj, database)
            union: dict[str, Any] = {}
            for _host_info, host_schema in per_host.items():
                for tbl_name, tbl_schema in host_schema.items():
                    if tbl_name not in union:
                        union[tbl_name] = tbl_schema
            return union

        _migrations_union: dict[str, Any] | None = None

        def _fallback_union() -> dict[str, Any]:
            nonlocal _migrations_union
            if _migrations_union is None:
                _migrations_union = _union_from_cluster(get_migrations_cluster())
            return _migrations_union

        all_diffs = []
        for cluster_name, states in by_cluster.items():
            used_fallback = False
            try:
                cluster_obj = get_cluster_by_name(cluster_name)
                current = _union_from_cluster(cluster_obj)
            except Exception as exc:
                exc_str = str(exc)
                is_unreachable = (
                    "CLUSTER_DOESNT_EXIST" in exc_str
                    or "Code: 701" in exc_str
                    or "Code: 210" in exc_str
                    or "Connection refused" in exc_str
                    or "Name or service not known" in exc_str
                    or "not found" in exc_str.lower()
                )
                if is_unreachable:
                    ecosystem_names = ", ".join(s.ecosystem for s in states)
                    print(
                        f"Warning: cluster '{cluster_name}' "
                        f"(ecosystems: {ecosystem_names}) unreachable; "
                        f"falling back to migrations-cluster schema. Details: {exc_str[:200]}"
                    )
                    try:
                        current = _fallback_union()
                        used_fallback = True
                    except Exception as fallback_exc:
                        print(f"Warning: fallback also failed for '{cluster_name}': {fallback_exc!s:.200}. Skipping.")
                        continue
                else:
                    raise

            for desired in states:
                ecosystem_current = {} if used_fallback else {n: t for n, t in current.items() if n in desired.tables}
                diffs = diff_state(desired, ecosystem_current, database=database)
                for d in diffs:
                    d.cluster = cluster_name
                    all_diffs.append(d)

            if used_fallback:
                continue

            for table_name in sorted(current.keys()):
                if table_name in all_desired_names or table_name in TRACKING_TABLES:
                    continue
                if table_name in all_placeholder_names:
                    continue
                current_table = current[table_name]
                all_diffs.append(
                    StateDiff(
                        action="drop",
                        table=table_name,
                        detail=f"Orphan: {table_name} exists but is not declared in any YAML on cluster {cluster_name}",
                        sql=_drop_stmt(current_table.engine, database, table_name),
                        node_roles=["ALL"],
                        cluster=cluster_name,
                    )
                )

        return all_diffs, None

    def handle_plan(self, options: dict[str, Any]) -> None:
        from pathlib import Path

        from posthog.clickhouse.migration_tools.plan_generator import generate_plan_text

        database: str = settings.CLICKHOUSE_DATABASE
        schema_dir = Path(options.get("schema_dir", DEFAULT_SCHEMA_DIR))
        if not schema_dir.exists():
            print(f"Schema directory not found: {schema_dir}")
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

        cluster_name = getattr(settings, "CLICKHOUSE_MIGRATIONS_CLUSTER", "posthog_migrations")
        acquired, reason = acquire_apply_lock(client, database, hostname, force=force, cluster=cluster_name)
        if not acquired:
            print(reason)
            return

        continue_on_error: bool = options.get("continue_on_error", False)
        failures: list[tuple[int, str, str]] = []

        cluster_cache: dict[str, Any] = {"": cluster_obj}

        def _resolve_step_cluster(step_cluster_name: str) -> Any:
            key = step_cluster_name or ""
            if key in cluster_cache:
                return cluster_cache[key]
            try:
                resolved = get_cluster_by_name(step_cluster_name)
            except Exception:
                resolved = cluster_obj
            cluster_cache[key] = resolved
            return resolved

        try:
            steps = generate_manifest_steps(all_diffs)
            print(f"Applying {len(steps)} step(s)...\n")

            max_retries = 3
            for i, (step, rendered_sql) in enumerate(steps):
                print(f"  Step {i}: {step.comment}...", end=" ", flush=True)
                checksum = hashlib.sha256(rendered_sql.encode()).hexdigest()
                step_cluster = _resolve_step_cluster(step.cluster)
                success = False
                last_exc: Exception | None = None
                for attempt in range(max_retries):
                    try:
                        execute_migration_step(step_cluster, step, rendered_sql)
                        success = True
                        break
                    except Exception as exc:
                        last_exc = exc
                        if attempt < max_retries - 1:
                            wait = 2**attempt
                            print(f"\n    Retry {attempt + 1}/{max_retries} in {wait}s: {exc}", flush=True)
                            time.sleep(wait)

                if not success:
                    assert last_exc is not None
                    print(f"FAILED after {max_retries} attempts: {last_exc}")
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
                    failures.append((i, step.comment or "reconcile", str(last_exc)))
                    if not continue_on_error:
                        print("\nApply halted. Pass --continue-on-error to surface all failures.")
                        raise CommandError(f"Apply failed on step {i} ({step.comment or 'reconcile'}): {last_exc}")
                    continue

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

        if failures:
            print(f"\n=== APPLY SUMMARY: {len(steps) - len(failures)} OK, {len(failures)} FAILED ===")
            for idx, name, err in failures:
                first_line = err.split("\n", 1)[0][:300]
                print(f"  step {idx} {name}: {first_line}")
            raise CommandError(f"Apply finished with {len(failures)} failure(s) out of {len(steps)} step(s)")

        try:
            result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                record_schema_version(client, database, result.stdout.strip(), hostname)
                print(f"Schema version recorded: {result.stdout.strip()[:12]}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        print("\nApply completed successfully.")
