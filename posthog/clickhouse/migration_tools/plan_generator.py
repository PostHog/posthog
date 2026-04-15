"""Generate human-readable plans and executable ManifestStep lists from StateDiffs.

Takes a list[StateDiff] from state_diff.diff_state() and produces:
1. A human-readable plan (like terraform plan) with +/-/~ symbols
2. A list of ManifestStep objects that the existing runner can execute
3. Rollback steps (reverse of the plan)
"""

from __future__ import annotations

from posthog.clickhouse.migration_tools.manifest import ManifestStep
from posthog.clickhouse.migration_tools.state_diff import StateDiff

# Map action to plan symbol
_ACTION_SYMBOL: dict[str, str] = {
    "create": "+",
    "drop": "-",
    "alter_add_column": "~",
    "alter_drop_column": "~",
    "alter_modify_column": "~",
    "recreate_mv": "-/+",
    "recreate": "-/+",
}


def generate_plan_text(diffs: list[StateDiff]) -> str:
    """Generate a human-readable plan string (like terraform plan output)."""
    if not diffs:
        return "No changes. Infrastructure is up to date."

    lines: list[str] = []

    # Kafka table recreate warning — ingestion pauses between DROP and CREATE
    kafka_recreates = [d for d in diffs if d.action in ("drop", "recreate") and "kafka" in d.table.lower()]
    if kafka_recreates:
        lines.append("\u26a0\ufe0f  KAFKA TABLE RECREATE WARNING")
        lines.append("=" * 60)
        for k in kafka_recreates:
            lines.append(f"  - {k.table}: ingestion will pause between DROP and CREATE.")
            lines.append("    Messages accumulating in Kafka during this window may be")
            lines.append("    lost if the topic retention expires. Consumer group offsets")
            lines.append("    reset. Dependent MaterializedViews will also need recreating.")
        lines.append("")
        lines.append("  Recommended: pause upstream producers or extend retention before applying.")
        lines.append("=" * 60)
        lines.append("")

    lines.append("ch_migrate plan:\n")

    creates = 0
    destroys = 0
    modifies = 0

    for diff in diffs:
        symbol = _ACTION_SYMBOL.get(diff.action, "?")
        if diff.action == "alter_modify_column":
            lines.append(
                f"  \u26a0 {diff.table:40s} ({diff.detail} \u2014 rewrites data, may take hours on large tables)"
            )
        else:
            lines.append(f"  {symbol} {diff.table:40s} ({diff.detail})")

        if diff.action == "create":
            creates += 1
        elif diff.action == "drop":
            destroys += 1
        elif diff.action in ("recreate", "recreate_mv"):
            destroys += 1
            creates += 1
        else:
            modifies += 1

    parts = []
    if modifies:
        parts.append(f"{modifies} to modify")
    if destroys:
        parts.append(f"{destroys} to destroy")
    if creates:
        parts.append(f"{creates} to create")

    lines.append(f"\nPlan: {', '.join(parts)}.")
    return "\n".join(lines)


def generate_manifest_steps(diffs: list[StateDiff]) -> list[tuple[ManifestStep, str]]:
    """Convert StateDiffs into ManifestStep + SQL pairs for the existing runner."""
    steps: list[tuple[ManifestStep, str]] = []

    for diff in diffs:
        if diff.action in ("recreate", "recreate_mv"):
            # Split into DROP + CREATE
            sql_parts = diff.sql.split(";\n", 1)
            if len(sql_parts) == 2:
                drop_sql, create_sql = sql_parts
                steps.append(
                    (
                        ManifestStep(
                            sql=f"_reconcile:drop_{diff.table}",
                            node_roles=diff.node_roles,
                            comment=f"Drop {diff.table} for recreation",
                            sharded=diff.sharded,
                            cluster=diff.cluster,
                        ),
                        drop_sql,
                    )
                )
                steps.append(
                    (
                        ManifestStep(
                            sql=f"_reconcile:create_{diff.table}",
                            node_roles=diff.node_roles,
                            comment=f"Recreate {diff.table}",
                            sharded=diff.sharded,
                            cluster=diff.cluster,
                        ),
                        create_sql,
                    )
                )
            else:
                steps.append(
                    (
                        ManifestStep(
                            sql=f"_reconcile:{diff.action}_{diff.table}",
                            node_roles=diff.node_roles,
                            comment=diff.detail,
                            sharded=diff.sharded,
                            cluster=diff.cluster,
                        ),
                        diff.sql,
                    )
                )
        else:
            steps.append(
                (
                    ManifestStep(
                        sql=f"_reconcile:{diff.action}_{diff.table}",
                        node_roles=diff.node_roles,
                        comment=diff.detail,
                        sharded=diff.sharded,
                        is_alter_on_replicated_table=diff.is_alter_on_replicated_table,
                        cluster=diff.cluster,
                    ),
                    diff.sql,
                )
            )

    return steps
