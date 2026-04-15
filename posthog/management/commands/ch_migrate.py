# ruff: noqa: T201 allow print statements
"""
ClickHouse schema management -- declarative, Terraform-style.

Subcommand (this slice):
  plan  -- diff schema/*.yaml vs live ClickHouse, show plan

Modules: desired_state, state_diff, plan_generator, schema_introspect.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.clickhouse.cluster import get_all_logical_clusters, get_cluster_by_name, is_known_cluster

DEFAULT_SCHEMA_DIR = "posthog/clickhouse/schema"


def _any_client(cluster: Any) -> Any:
    return cluster.any_host(lambda c: c).result()


class Command(BaseCommand):
    help = "ClickHouse schema management -- plan"

    def add_arguments(self, parser: Any) -> None:
        subparsers = parser.add_subparsers(dest="subcommand")

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

    def handle(self, *args: Any, **options: Any) -> None:
        subcommand = options.get("subcommand")
        handlers: dict[str, Any] = {
            "plan": self.handle_plan,
        }
        handler = handlers.get(subcommand or "")
        if handler:
            handler(options)
        else:
            self.print_help("manage.py", "ch_migrate")

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
                    f"Known clusters: {known}. "
                    f"Add '{ds.cluster}' to _REGISTRY in posthog/clickhouse/cluster.py with the "
                    f"appropriate CLICKHOUSE_*_HOST and CLICKHOUSE_*_CLUSTER settings."
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
                        print(
                            f"Warning: fallback to migrations cluster also failed for "
                            f"'{cluster_name}': {fallback_exc!s:.200}. Skipping."
                        )
                        continue
                else:
                    raise

            for desired in states:
                if used_fallback:
                    ecosystem_current = {}
                else:
                    ecosystem_current = {name: table for name, table in current.items() if name in desired.tables}
                diffs = diff_state(desired, ecosystem_current, database=database)
                for d in diffs:
                    d.cluster = cluster_name
                    all_diffs.append(d)

            if used_fallback:
                continue

            for table_name in sorted(current.keys()):
                if table_name in all_desired_names:
                    continue
                if table_name in TRACKING_TABLES:
                    continue
                if table_name in all_placeholder_names:
                    continue
                current_table = current[table_name]
                all_diffs.append(
                    StateDiff(
                        action="drop",
                        table=table_name,
                        detail=(
                            f"Orphan: table {table_name} exists but is not declared in any "
                            f"YAML on cluster {cluster_name}"
                        ),
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
