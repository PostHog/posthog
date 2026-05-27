"""Markdown report renderer for analyze_migration_profile.

Reads the JSONL files written by ``profile_migrations`` (one per DB alias),
plus optional py-spy raw files, and produces a single Markdown report with
the sections enumerated in the design doc.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from posthog.management.migration_profiling.dead_code.models import Finding
from posthog.management.migration_profiling.dead_code.waste_analysis import (
    AVOIDABLE_CATEGORIES,
    WasteBreakdown,
    WasteCategory,
)
from posthog.management.migration_profiling.pyinstrument_parse import PyinstrumentAggregate
from posthog.management.migration_profiling.spy import SpyAggregate

TOP_OPS = 50
TOP_MIGRATIONS = 30
TOP_SQL = 30
TOP_PY_FUNCS = 30
P95 = 0.95


@dataclass
class ProfileRun:
    meta: dict[str, Any]
    ops: list[dict[str, Any]]
    # Per-migration apply summaries — wall-clock of Migration.apply, which
    # captures state_forwards + project_state cloning + database_forwards.
    # Keyed by (app_label, migration_name) → apply_duration_ms.
    migration_summaries: dict[tuple[str, str], float] = field(default_factory=dict)
    # Per-state-op timings (`_kind: state_op` records from the profiler). Kept
    # separate from `ops` because they lack `sql_count`/`sql_statements` and
    # would break the database_forwards-centric aggregators.
    state_ops: list[dict[str, Any]] = field(default_factory=list)

    @property
    def database(self) -> str:
        return self.meta.get("database", "<unknown>")


def load_run(path: Path) -> ProfileRun:
    meta: dict[str, Any] = {}
    ops: list[dict[str, Any]] = []
    state_ops: list[dict[str, Any]] = []
    summaries: dict[tuple[str, str], float] = {}
    with open(path) as fp:
        for line_no, raw in enumerate(fp, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} not valid JSON: {exc}") from exc
            if "_meta" in record:
                meta = record["_meta"]
            elif record.get("_kind") == "migration_summary":
                summaries[(record["app_label"], record["migration_name"])] = record["apply_duration_ms"]
            elif record.get("_kind") == "state_op":
                state_ops.append(record)
            else:
                ops.append(record)
    return ProfileRun(meta=meta, ops=ops, migration_summaries=summaries, state_ops=state_ops)


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f}s"
    if ms >= 1:
        return f"{ms:.1f}ms"
    return f"{ms:.3f}ms"


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    try:
        # statistics.quantiles is more robust than custom indexing.
        return statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]
    except statistics.StatisticsError:
        return max(values)


def _is_state_only(op: dict[str, Any]) -> bool:
    return bool(op.get("is_state_only"))


def _has_children(
    op: dict[str, Any], parent_index: tuple[str, str, int], children_index: dict[tuple[str, str, int], int]
) -> bool:
    return children_index.get(parent_index, 0) > 0


def _build_children_index(ops: list[dict[str, Any]]) -> dict[tuple[str, str, int], int]:
    """Count how many ops point at each ``(app, migration, op_index)`` as their parent."""
    counts: dict[tuple[str, str, int], int] = defaultdict(int)
    for op in ops:
        parent = op.get("parent_op_index")
        if parent is None:
            continue
        counts[(op["app_label"], op["migration_name"], parent)] += 1
    return counts


def _effective_ops(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ops we count in totals — exclude state-only ops, exclude
    ``SeparateDatabaseAndState`` outers that have children (to avoid
    double-counting their inner ops)."""
    children = _build_children_index(ops)
    out = []
    for op in ops:
        if _is_state_only(op):
            continue
        key = (op["app_label"], op["migration_name"], op.get("operation_index", -1))
        if op["operation_type"] == "SeparateDatabaseAndState" and children.get(key, 0) > 0:
            continue
        out.append(op)
    return out


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Plain pipe-table renderer. Empty rows → ``_no entries_``."""
    if not rows:
        return "_no entries_\n"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) if c is not None else "" for c in row) + " |")
    return "\n".join(lines) + "\n"


def render_report(
    runs: list[ProfileRun],
    spy_results: dict[str, tuple[SpyAggregate, Path | None]],
    pyinstrument_paths: dict[str, Path] | None = None,
    pyinstrument_aggregates: dict[str, PyinstrumentAggregate] | None = None,
    findings: list[Finding] | None = None,
    waste: WasteBreakdown | None = None,
) -> str:
    """Build the full Markdown report."""
    pyinstrument_paths = pyinstrument_paths or {}
    pyinstrument_aggregates = pyinstrument_aggregates or {}
    findings = findings or []

    # ---- executive summary (computed up front) ----
    all_ops_local = [op for run in runs for op in _effective_ops(run.ops)]
    sql_total_ms = sum(op["duration_ms"] for op in all_ops_local)
    apply_total_ms = sum(s for run in runs for s in run.migration_summaries.values())
    pyinstrument_total_s = sum(a.total_duration_s for a in pyinstrument_aggregates.values())
    # python overhead = apply_total - sql_total (positive = state-machine cost)
    python_overhead_ms = max(apply_total_ms - sql_total_ms, 0.0) if apply_total_ms else 0.0
    overhead_share = (python_overhead_ms / apply_total_ms * 100.0) if apply_total_ms else 0.0
    total_migrations = sum(len(run.migration_summaries) for run in runs) or len(
        {(op["app_label"], op["migration_name"]) for op in all_ops_local}
    )
    sdas_noop_count = sum(
        1 for op in all_ops_local if op["operation_type"] == "SeparateDatabaseAndState" and op["duration_ms"] < 1.0
    )
    parts: list[str] = []
    parts.append("# Migration profile report\n")

    # ---- waste distribution (top of report) ----
    if waste and waste.apply_total_ms:
        parts.append("\n## Where does the time go?\n\n")
        parts.append(_waste_distribution_section(waste))

    # ---- executive summary ----
    parts.append("\n## Executive summary\n\n")
    parts.append(f"- **Migrations applied**: {total_migrations}\n")
    parts.append(f"- **Operations recorded**: {len(all_ops_local)}\n")
    if apply_total_ms:
        parts.append(f"- **Total `Migration.apply` wall-clock**: {_fmt_ms(apply_total_ms)}\n")
    if pyinstrument_total_s:
        parts.append(f"- **Total Python runtime (pyinstrument)**: {pyinstrument_total_s:.1f}s\n")
    parts.append(f"- **SQL / DB time (sum of `database_forwards`)**: {_fmt_ms(sql_total_ms)}\n")
    if python_overhead_ms:
        parts.append(
            f"- **Python state-machine overhead**: {_fmt_ms(python_overhead_ms)} "
            f"(**{overhead_share:.0f}%** of apply time)\n"
        )
    if sdas_noop_count:
        parts.append(
            f"- **`SeparateDatabaseAndState` no-op operations** (0 DB work, full Python tax): {sdas_noop_count}\n"
        )
    parts.append(
        "\nThe headline cost is **Django's project-state machine**, not SQL. "
        "Squashing matters because every migration triggers `state.clone()` "
        "and `state.render()` against every loaded model — see the "
        "`Python state machine` section below for the hottest functions, and "
        "the `Squash candidates` section for migrations where the SQL cost is "
        "negligible but the Python tax compounds.\n"
    )

    # ---- top opportunities (synthesized) ----
    parts.append("\n## Top opportunities\n\n")
    parts.append(_top_opportunities_section(runs, all_ops_local, findings, waste))

    # ---- dead-code findings (AST detectors) ----
    if findings:
        parts.append("\n## Dead-code findings\n\n")
        parts.append(_findings_section(findings))

    # ---- run metadata ----
    parts.append("\n## Run metadata\n")
    meta_rows = []
    for run in runs:
        meta_rows.append(
            [
                run.database,
                run.meta.get("started_at", ""),
                run.meta.get("django_version", ""),
                (run.meta.get("git_sha") or "")[:12],
                len(run.ops),
            ]
        )
    parts.append(_md_table(["Database", "Started at", "Django", "Git SHA", "Ops captured"], meta_rows))

    # ---- aggregates ----
    all_ops = [op for run in runs for op in _effective_ops(run.ops)]
    parts.append("\n## Aggregates\n")
    parts.append("\n### By database\n")
    parts.append(_md_table(*_agg_by_database(runs)))
    parts.append("\n### By app\n")
    parts.append(_md_table(*_agg_by_app(all_ops)))
    parts.append("\n### By operation type\n")
    parts.append(_md_table(*_agg_by_optype(all_ops)))

    # ---- slowest ops ----
    parts.append(f"\n## Top {TOP_OPS} slowest operations\n")
    parts.append(_md_table(*_slowest_ops(all_ops)))

    # ---- slowest migrations ----
    summaries_by_db = {run.database: run.migration_summaries for run in runs}
    parts.append(f"\n## Top {TOP_MIGRATIONS} slowest migrations\n")
    parts.append(_md_table(*_slowest_migrations(all_ops, summaries_by_db, waste)))

    # ---- slowest SQL ----
    parts.append(f"\n## Top {TOP_SQL} slowest SQL statements\n")
    parts.append(_md_table(*_slowest_sql(all_ops)))

    # ---- squash candidates ----
    parts.append("\n## Squash candidates (fast & small)\n")
    parts.append(_md_table(*_squash_candidates(all_ops)))

    # ---- useless-on-fresh-DB RunPython ----
    parts.append("\n## RunPython operations that are no-ops on a fresh DB\n")
    parts.append(_useless_runpython_section(runs))

    # ---- squash impact estimate ----
    if any(run.migration_summaries for run in runs):
        parts.append("\n## Squash impact estimate\n")
        parts.append(_squash_impact_section(runs))

    # ---- squash clusters (consecutive low-cost migrations) ----
    if any(run.migration_summaries for run in runs):
        parts.append("\n## Squash clusters (consecutive low-cost migrations)\n")
        parts.append(_squash_clusters_section(runs))

    # ---- do not touch ----
    parts.append("\n## Heavy migrations (skip squashing)\n")
    parts.append(_md_table(*_heavy_migrations(all_ops)))

    # ---- pyinstrument ----
    if pyinstrument_aggregates or pyinstrument_paths:
        parts.append("\n## Python state machine (pyinstrument)\n")
        for db, agg in pyinstrument_aggregates.items():
            parts.append(f"\n### {db}\n")
            parts.append(
                f"\nTotal duration: {agg.total_duration_s:.1f}s"
                + (f" ({agg.sample_count} samples)" if agg.sample_count else "")
                + "\n"
            )
            if db in pyinstrument_paths:
                parts.append(f"\nInteractive HTML: [`{pyinstrument_paths[db].name}`]({pyinstrument_paths[db].name})\n")
            parts.append("\n#### Top by self time\n")
            parts.append(
                _md_table(
                    ["Function", "Self s", "% of total"],
                    [[fn, f"{t:.2f}", f"{p:.1f}%"] for fn, t, p in agg.by_self[:TOP_PY_FUNCS]],
                )
            )
            parts.append("\n#### Top by cumulative time\n")
            parts.append(
                _md_table(
                    ["Function", "Cumulative s", "% of total"],
                    [[fn, f"{t:.2f}", f"{p:.1f}%"] for fn, t, p in agg.by_cumulative[:TOP_PY_FUNCS]],
                )
            )
        # If we only have HTML paths (no JSON), still link them.
        only_html = [db for db in pyinstrument_paths if db not in pyinstrument_aggregates]
        if only_html:
            parts.append("\n### HTML reports (no inline aggregate available)\n")
            for db in only_html:
                parts.append(f"- {db}: [`{pyinstrument_paths[db].name}`]({pyinstrument_paths[db].name})\n")

    # ---- py-spy ----
    if spy_results:
        parts.append("\n## Python hot functions (py-spy)\n")
        for db, (agg, svg_path) in spy_results.items():
            parts.append(f"\n### {db}\n")
            parts.append(f"Total samples: {agg.total_samples}\n")
            if svg_path is not None:
                parts.append(f"\nFlame graph: [`{svg_path.name}`]({svg_path.name})\n")
            parts.append("\n#### Top by self time\n")
            parts.append(
                _md_table(
                    ["Function", "Samples", "% of total"],
                    [[fn, n, f"{p:.1f}%"] for fn, n, p in agg.by_self[:TOP_PY_FUNCS]],
                )
            )
            parts.append("\n#### Top by cumulative time\n")
            parts.append(
                _md_table(
                    ["Function", "Samples", "% of total"],
                    [[fn, n, f"{p:.1f}%"] for fn, n, p in agg.by_cumulative[:TOP_PY_FUNCS]],
                )
            )

    return "".join(parts)


# ---------- aggregates ----------


def _agg_by_database(runs: list[ProfileRun]) -> tuple[list[str], list[list[Any]]]:
    rows = []
    for run in runs:
        effective = _effective_ops(run.ops)
        total_ms = sum(op["duration_ms"] for op in effective)
        durations = [op["duration_ms"] for op in effective if op["duration_ms"] > 0]
        rows.append(
            [
                run.database,
                len({(op["app_label"], op["migration_name"]) for op in effective}),
                len(effective),
                _fmt_ms(total_ms),
                _fmt_ms(_percentile(durations, P95)),
            ]
        )
    return ["Database", "Migrations", "Ops", "Total", "p95 op"], rows


def _agg_by_app(ops: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    by_app: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for op in ops:
        by_app[op["app_label"]].append(op)
    rows = []
    for app, app_ops in sorted(by_app.items(), key=lambda x: -sum(o["duration_ms"] for o in x[1])):
        total_ms = sum(op["duration_ms"] for op in app_ops)
        rows.append(
            [
                app,
                len({(op["app_label"], op["migration_name"]) for op in app_ops}),
                len(app_ops),
                _fmt_ms(total_ms),
            ]
        )
    return ["App", "Migrations", "Ops", "Total"], rows


def _agg_by_optype(ops: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    by_type: dict[str, list[float]] = defaultdict(list)
    for op in ops:
        by_type[op["operation_type"]].append(op["duration_ms"])
    rows = []
    for op_type, durations in sorted(by_type.items(), key=lambda x: -sum(x[1])):
        rows.append(
            [
                op_type,
                len(durations),
                _fmt_ms(sum(durations)),
                _fmt_ms(statistics.median(durations) if durations else 0.0),
                _fmt_ms(_percentile(durations, P95)),
                _fmt_ms(max(durations) if durations else 0.0),
            ]
        )
    return ["Op type", "Count", "Total", "p50", "p95", "Max"], rows


# ---------- listings ----------


def _slowest_ops(ops: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    sorted_ops = sorted(ops, key=lambda o: -o["duration_ms"])[:TOP_OPS]
    rows = []
    for i, op in enumerate(sorted_ops, start=1):
        rows.append(
            [
                i,
                op["database"],
                op["app_label"],
                op["migration_name"],
                op["operation_type"],
                op["describe"][:80],
                _fmt_ms(op["duration_ms"]),
                op["sql_count"],
            ]
        )
    return (
        ["#", "DB", "App", "Migration", "Op", "Describe", "Duration", "SQL"],
        rows,
    )


_ALWAYS_AVOIDABLE_OP_TYPES: frozenset[str] = frozenset(
    {
        "RunPython",
        "RemoveField",
        "RemoveIndex",
        "RemoveIndexConcurrently",
        "DeleteModel",
        "RemoveConstraint",
        "SeparateDatabaseAndState",
        "AlterModelOptions",
        "AlterModelManagers",
        "AlterOrderWithRespectTo",
    }
)


def _verdict_for_ops(key_ops: list[dict[str, Any]]) -> str:
    """Heuristic per-migration verdict from the op-type mix.

    A migration whose every op is in :data:`_ALWAYS_AVOIDABLE_OP_TYPES` is
    "fully avoidable" — none of its operations build alive schema. Migrations
    with at least one essential-shaped op are "essential" or "mixed". Doesn't
    catch dead-target ops (those need the alive set) but it captures the
    high-signal cases.
    """
    total = len(key_ops)
    if total == 0:
        return ""
    avoidable_count = sum(
        1 for op in key_ops if op["operation_type"] in _ALWAYS_AVOIDABLE_OP_TYPES or op.get("is_state_only")
    )
    if avoidable_count == total:
        return "fully avoidable"
    if avoidable_count == 0:
        return "essential"
    return f"mixed ({avoidable_count}/{total} avoidable)"


def _slowest_migrations(
    ops: list[dict[str, Any]],
    summaries_by_db: dict[str, dict[tuple[str, str], float]] | None = None,
    waste: WasteBreakdown | None = None,
) -> tuple[list[str], list[list[Any]]]:
    summaries_by_db = summaries_by_db or {}
    by_mig: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for op in ops:
        by_mig[(op["database"], op["app_label"], op["migration_name"])].append(op)

    def _migration_verdict(key_ops: list[dict[str, Any]]) -> str:
        if waste is None:
            return ""
        return _verdict_for_ops(key_ops)

    aggregates = []
    for key, key_ops in by_mig.items():
        db, app, name = key
        sql_total = sum(op["duration_ms"] for op in key_ops)
        apply_total = summaries_by_db.get(db, {}).get((app, name))
        rank_total = apply_total if apply_total is not None else sql_total
        heaviest = max(key_ops, key=lambda o: o["duration_ms"])
        verdict = _migration_verdict(key_ops)
        aggregates.append((key, rank_total, sql_total, apply_total, len(key_ops), heaviest, verdict))
    aggregates.sort(key=lambda x: -x[1])
    rows = []
    for i, (key, _rank, sql_total, apply_total, n_ops, heaviest, verdict) in enumerate(
        aggregates[:TOP_MIGRATIONS], start=1
    ):
        python_overhead = ""
        apply_cell = ""
        if apply_total is not None:
            apply_cell = _fmt_ms(apply_total)
            python_overhead = _fmt_ms(max(apply_total - sql_total, 0.0))
        rows.append(
            [
                i,
                key[0],
                key[1],
                key[2],
                apply_cell or "—",
                _fmt_ms(sql_total),
                python_overhead or "—",
                n_ops,
                verdict or "—",
                f"{heaviest['operation_type']} ({_fmt_ms(heaviest['duration_ms'])})",
            ]
        )
    return (
        ["#", "DB", "App", "Migration", "Apply total", "SQL", "Python overhead", "Ops", "Verdict", "Heaviest op"],
        rows,
    )


def _slowest_sql(ops: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    flattened: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for op in ops:
        for stmt in op.get("sql_statements", []):
            flattened.append((op, stmt))
    flattened.sort(key=lambda x: -x[1]["duration_ms"])
    rows = []
    for i, (op, stmt) in enumerate(flattened[:TOP_SQL], start=1):
        rows.append(
            [
                i,
                op["app_label"] + "." + op["migration_name"],
                op["operation_type"],
                stmt["source"],
                _fmt_ms(stmt["duration_ms"]),
                stmt["sql"][:120].replace("|", "\\|"),
            ]
        )
    return ["#", "Migration", "Op", "Source", "Duration", "SQL"], rows


def _squash_candidates(ops: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    by_mig: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for op in ops:
        by_mig[(op["database"], op["app_label"], op["migration_name"])].append(op)
    candidates = []
    for key, key_ops in by_mig.items():
        total = sum(op["duration_ms"] for op in key_ops)
        if total < 100.0 and len(key_ops) <= 3:
            candidates.append((key, total, key_ops))
    candidates.sort(key=lambda x: x[1])
    rows = []
    for key, total, key_ops in candidates[:100]:
        op_types = ", ".join(op["operation_type"] for op in key_ops)
        rows.append([key[0], key[1], key[2], _fmt_ms(total), len(key_ops), op_types[:80]])
    return ["DB", "App", "Migration", "Duration", "Ops", "Op types"], rows


_CATEGORY_LABELS: dict[str, str] = {
    WasteCategory.ESSENTIAL_CREATE: "Essential creates",
    WasteCategory.ESSENTIAL_RESHAPE: "Essential reshapes",
    WasteCategory.REDUNDANT_RESHAPE: "Redundant reshapes",
    WasteCategory.DEAD_TARGET: "Ops on dead targets",
    WasteCategory.REMOVAL: "Removals",
    WasteCategory.BACKFILL: "RunPython backfills (no rows on fresh DB)",
    WasteCategory.STATE_ONLY: "State-only ops (SDAS etc.)",
    WasteCategory.BOOTSTRAP: "Bootstrap DDL",
    WasteCategory.UNKNOWN: "Unclassified",
}


def _waste_distribution_section(waste: WasteBreakdown) -> str:
    """Render the headline 'where does the time go' breakdown.

    The framing: the final schema is the goal. The cheapest way to reach it
    is one squashed initial migration. Time spent beyond that is reclaimable.
    """
    apply_total = waste.apply_total_ms
    essential_sql = waste.essential_sql_ms
    avoidable_sql = waste.avoidable_sql_ms
    sm_total = waste.state_machine_total_ms
    floor = waste.theoretical_floor_ms
    avoidable = waste.total_avoidable_ms
    avoid_pct = waste.avoidable_share * 100.0

    parts: list[str] = []
    parts.append(
        f"**Of {_fmt_ms(apply_total)} total `Migration.apply` wall-clock, "
        f"~{_fmt_ms(avoidable)} ({avoid_pct:.0f}%) is reclaimable if you re-squash to the final schema.**\n\n"
        f"Theoretical floor: ~{_fmt_ms(floor)} — what it would cost to build "
        "the current schema as one mega-squashed initial migration. Everything "
        "above that line is migration history overhead.\n\n"
    )

    # Top-level slabs (the bar's view).
    slab_rows = [
        [
            "Essential SQL (final schema construction)",
            _fmt_ms(essential_sql),
            f"{essential_sql / apply_total * 100:.1f}%",
            "essential",
        ],
        [
            "Avoidable SQL (dead targets, backfills, etc.)",
            _fmt_ms(avoidable_sql),
            f"{avoidable_sql / apply_total * 100:.1f}%",
            "avoidable",
        ],
        [
            "Django state-machine (squashable to ~1 pass)",
            _fmt_ms(sm_total),
            f"{sm_total / apply_total * 100:.1f}%",
            f"~{_fmt_ms(min(sm_total, waste.ONE_MIGRATION_APPLY_FLOOR_MS))} stays, rest amortizes",
        ],
    ]
    parts.append("### Top-level breakdown\n\n")
    parts.append(_md_table(["Category", "Time", "% of total", "Verdict"], slab_rows))

    parts.append("\n### Per-operation SQL breakdown\n\n")
    rows: list[list[Any]] = []
    for cat in (
        WasteCategory.ESSENTIAL_CREATE,
        WasteCategory.ESSENTIAL_RESHAPE,
        WasteCategory.REDUNDANT_RESHAPE,
        WasteCategory.DEAD_TARGET,
        WasteCategory.REMOVAL,
        WasteCategory.BACKFILL,
        WasteCategory.STATE_ONLY,
        WasteCategory.BOOTSTRAP,
        WasteCategory.UNKNOWN,
    ):
        ms = waste.sql_ms_by_category.get(cat, 0.0)
        n = waste.op_count_by_category.get(cat, 0)
        if ms <= 0 and n == 0:
            continue
        pct = ms / apply_total * 100.0 if apply_total else 0.0
        verdict = "avoidable" if cat in AVOIDABLE_CATEGORIES else "essential"
        rows.append([_CATEGORY_LABELS[cat], n, _fmt_ms(ms), f"{pct:.1f}%", verdict])
    parts.append(_md_table(["Category", "Ops", "Time", "% of total", "Verdict"], rows))

    # ASCII bar: three slabs (essential SQL / avoidable SQL / state machine).
    parts.append("\n```\n")
    parts.append(_ascii_three_slab_bar(essential_sql, avoidable_sql, sm_total, apply_total))
    parts.append("\n```\n")

    return "".join(parts)


def _ascii_three_slab_bar(essential_sql: float, avoidable_sql: float, sm: float, total: float, width: int = 60) -> str:
    if total <= 0:
        return ""
    es_chars = max(int(round(essential_sql / total * width)), 1 if essential_sql > 0 else 0)
    av_chars = max(int(round(avoidable_sql / total * width)), 1 if avoidable_sql > 0 else 0)
    sm_chars = max(width - es_chars - av_chars, 0)
    bar = "[" + "#" * es_chars + "X" * av_chars + "~" * sm_chars + "]"
    legend = f"  # essential SQL ({essential_sql / total * 100:.0f}%)  X avoidable SQL ({avoidable_sql / total * 100:.0f}%)  ~ state machine ({sm / total * 100:.0f}%)"
    return bar + legend


def _findings_section(findings: list[Finding]) -> str:
    """Render the AST-detector findings as a per-detector breakdown.

    Findings are grouped by detector + confidence tier so the eye can scan
    "what's safe to act on" first.
    """
    by_detector: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_detector[f.detector_name].append(f)

    parts: list[str] = []
    for detector_name, hits in sorted(by_detector.items(), key=lambda kv: -len(kv[1])):
        parts.append(f"### `{detector_name}` ({len(hits)} hits)\n\n")
        # Confidence histogram for the detector.
        tier_counts: dict[str, int] = defaultdict(int)
        for f in hits:
            tier_counts[f.confidence_tier.value] += 1
        bits = []
        for tier in ("high", "medium", "low"):
            n = tier_counts.get(tier, 0)
            if n:
                bits.append(f"{n} {tier}")
        if bits:
            parts.append("_Confidence: " + ", ".join(bits) + "_\n\n")
        rows = []
        for f in sorted(hits, key=lambda x: -x.confidence)[:50]:
            migs = ", ".join(f"`{a}.{n}`" for a, n in f.migrations[:3])
            if len(f.migrations) > 3:
                migs += f" (+{len(f.migrations) - 3} more)"
            rows.append([f.confidence_tier.value, f.summary, migs])
        parts.append(_md_table(["Confidence", "Finding", "Migrations"], rows))
        parts.append("\n")
    return "".join(parts)


def _top_opportunities_section(
    runs: list[ProfileRun],
    all_ops: list[dict[str, Any]],
    findings: list[Finding] | None = None,
    waste: WasteBreakdown | None = None,
) -> str:
    """Synthesize a short prioritized action list from the rest of the report.

    Each item is ranked by ``estimated_savings_ms × ease`` where ``ease`` is
    a 1-3 heuristic (3 = safe after audit, 1 = needs design work). Items with
    zero estimated savings are skipped. The intent is a punch list a human
    can walk down: each row points to a concrete migration set or SQL pattern.
    """
    items: list[tuple[str, str, float, int]] = []  # (title, detail, savings_ms, ease)
    findings = findings or []

    # 0a. Headline: re-squash to floor. This dominates everything else and
    # makes the smaller opportunities subsets of itself.
    if waste and waste.apply_total_ms:
        reclaimable = waste.total_avoidable_ms
        floor = waste.theoretical_floor_ms
        items.append(
            (
                "Re-squash all migrations into one initial",
                f"Total Migration.apply is {_fmt_ms(waste.apply_total_ms)}. Theoretical floor "
                f"(one squashed initial with the current schema): ~{_fmt_ms(floor)}. "
                f"Everything else (~{_fmt_ms(reclaimable)}) is Django state-rebuild around dead "
                "operations and historical reshapes. See _Where does the time go?_. "
                "Subsumes all the smaller opportunities below.",
                reclaimable,
                1,  # not literally easy, but the ROI dwarfs everything else
            )
        )

    # 0b. AST-detected dead code (highest confidence findings are safest of all).
    high_conf_findings = [f for f in findings if f.confidence >= 0.9]
    if high_conf_findings:
        # Group by detector for the headline.
        from collections import Counter

        per_detector = Counter(f.detector_name for f in high_conf_findings)
        # Estimate savings: for now use the count × avg-low-SQL-apply-ms as a
        # rough proxy. Real value lives in the per-finding detail.
        items.append(
            (
                f"Audit and remove {len(high_conf_findings)} HIGH-confidence dead-code findings",
                "AST scan found mechanical dead-code (e.g. AddField/RemoveField loops, empty RunPython). "
                + " ".join(f"`{name}`: {n}" for name, n in per_detector.most_common())
                + ". See _Dead-code findings_.",
                float(len(high_conf_findings)) * 100.0,  # placeholder ms-equivalent
                3,
            )
        )

    # 1. RunPython no-ops on fresh DB (high impact, mechanical to remove)
    inert_or_drained = [
        op
        for op in all_ops
        if op["operation_type"] == "RunPython" and _classify_runpython(op) in ("inert", "read-only-empty")
    ]
    if inert_or_drained:
        wasted = sum(op["duration_ms"] for op in inert_or_drained)
        items.append(
            (
                f"Delete {len(inert_or_drained)} RunPython ops that do nothing on a fresh DB",
                f"Saves {_fmt_ms(wasted)} of DB-side time + the Python state-rebuild around each one. "
                "See _RunPython operations that are no-ops on a fresh DB_.",
                wasted,
                3,
            )
        )

    # 2. SeparateDatabaseAndState no-ops (zero DB work, full Python tax)
    sdas_noops = [
        op for op in all_ops if op["operation_type"] == "SeparateDatabaseAndState" and op["duration_ms"] < 1.0
    ]
    if sdas_noops:
        # Their cost lives in Migration.apply (state-rebuild), not in op duration.
        sdas_apply_total = 0.0
        sdas_set = {(op["database"], op["app_label"], op["migration_name"]) for op in sdas_noops}
        for run in runs:
            for (app, name), apply_ms in run.migration_summaries.items():
                if (run.database, app, name) in sdas_set:
                    sdas_apply_total += apply_ms
        items.append(
            (
                f"Squash {len(sdas_noops)} `SeparateDatabaseAndState` no-op migrations",
                f"Each is 0ms of SQL but the Migration.apply wall-clock sums to {_fmt_ms(sdas_apply_total)} "
                "in pure Django state-rebuild. Fold into their neighbours.",
                sdas_apply_total,
                3,
            )
        )

    # 3. Clusters of consecutive low-cost migrations
    CLUSTER_MAX_MS = 200.0
    MIN_CLUSTER_SIZE = 5
    by_app: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for run in runs:
        for (app, name), apply_ms in run.migration_summaries.items():
            by_app[(run.database, app)].append((name, apply_ms))
    cluster_savings = 0.0
    cluster_count = 0
    for (_db, _app), pairs in by_app.items():
        pairs.sort(key=lambda x: x[0])
        i = 0
        while i < len(pairs):
            if pairs[i][1] >= CLUSTER_MAX_MS:
                i += 1
                continue
            j = i
            total = 0.0
            while j < len(pairs) and pairs[j][1] < CLUSTER_MAX_MS:
                total += pairs[j][1]
                j += 1
            count = j - i
            if count >= MIN_CLUSTER_SIZE:
                cluster_savings += total * (count - 1) / count
                cluster_count += 1
            i = j
    if cluster_count:
        items.append(
            (
                f"Batch-squash {cluster_count} clusters of consecutive low-cost migrations",
                f"Each cluster of {MIN_CLUSTER_SIZE}+ migrations <{CLUSTER_MAX_MS:.0f}ms can fold into one. "
                f"Estimated savings: {_fmt_ms(cluster_savings)}. See _Squash clusters_.",
                cluster_savings,
                2,
            )
        )

    # 4. Single heaviest RunPython that's actually doing useful work — worth
    # rewriting as a one-shot SQL or moving out of migrations.
    active_runpython = [
        op for op in all_ops if op["operation_type"] == "RunPython" and _classify_runpython(op) == "active"
    ]
    active_runpython.sort(key=lambda op: -op["duration_ms"])
    if active_runpython:
        slowest = active_runpython[0]
        callable_name = (slowest.get("metadata") or {}).get("callable", "?")
        items.append(
            (
                f"Replace heaviest active RunPython: `{slowest['app_label']}.{slowest['migration_name']}`",
                f"Callable `{callable_name}` took {_fmt_ms(slowest['duration_ms'])} of real DB work. "
                "Rewrite as one-shot RunSQL or move outside migrations.",
                slowest["duration_ms"],
                1,
            )
        )

    # 5. Slowest single SQL statement — does it warrant a CONCURRENTLY / staged
    # approach?
    flat_sql: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for op in all_ops:
        for stmt in op.get("sql_statements") or []:
            flat_sql.append((op, stmt))
    flat_sql.sort(key=lambda x: -x[1]["duration_ms"])
    if flat_sql:
        op, stmt = flat_sql[0]
        if stmt["duration_ms"] > 50.0:
            items.append(
                (
                    f"Review slowest SQL in `{op['app_label']}.{op['migration_name']}`",
                    f"Single statement took {_fmt_ms(stmt['duration_ms'])} ({stmt['source']}). "
                    "On a populated production DB this likely scales with row count.",
                    stmt["duration_ms"],
                    1,
                )
            )

    if not items:
        return "_no opportunities identified — congrats?_\n"

    # Rank by impact × ease.
    items.sort(key=lambda x: -(x[2] * x[3]))

    out = "_Auto-synthesized punch list, ranked by impact × ease. Each row points at a section below._\n\n"
    rows = []
    ease_label = {3: "easy", 2: "medium", 1: "hard"}
    for title, detail, savings, ease in items:
        rows.append([title, _fmt_ms(savings), ease_label.get(ease, "?"), detail])
    out += _md_table(["Opportunity", "Est. savings", "Effort", "Detail"], rows)
    return out


def _classify_runpython(op: dict[str, Any]) -> str:
    """Classify a RunPython op by what SQL it actually executed.

    Returns one of:

    - ``"inert"``: ran no SQL at all. Pure no-op on fresh DB.
    - ``"read-only-empty"``: ran only SELECT/SHOW statements, all fast. The
      classic "look for rows to fix, find none, exit" pattern — useless on a
      fresh DB.
    - ``"read-only"``: ran only SELECT/SHOW but took noticeable time. Might
      still be doing meaningful work via Python branching on the results.
    - ``"active"``: ran at least one INSERT/UPDATE/DELETE/ALTER/CREATE/DROP/
      TRUNCATE. Real work — keep.
    """
    statements = op.get("sql_statements") or []
    sql_count = op.get("sql_count", len(statements))
    if sql_count == 0:
        return "inert"

    has_mutation = False
    total_ms = 0.0
    for stmt in statements:
        sql_text = (stmt.get("sql") or "").lstrip().upper()
        total_ms += stmt.get("duration_ms", 0.0)
        for kw in ("INSERT", "UPDATE", "DELETE", "ALTER ", "CREATE ", "DROP ", "TRUNCATE", "REINDEX"):
            if sql_text.startswith(kw):
                has_mutation = True
                break
        if has_mutation:
            break

    if has_mutation:
        return "active"
    if total_ms < 5.0:
        return "read-only-empty"
    return "read-only"


def _useless_runpython_section(runs: list[ProfileRun]) -> str:
    """List RunPython ops that did nothing observable to the DB.

    These are the strongest squash candidates: their original purpose (backfill
    data, fix corruption, migrate format) is meaningless on a fresh DB because
    there's no pre-existing data to act on. They still cost Django state-rebuild
    time on every fresh-DB run — pure deadweight.
    """
    categorized: dict[str, list[dict[str, Any]]] = {
        "inert": [],
        "read-only-empty": [],
        "read-only": [],
        "active": [],
    }
    for run in runs:
        for op in _effective_ops(run.ops):
            if op["operation_type"] != "RunPython":
                continue
            kind = _classify_runpython(op)
            categorized[kind].append(op)

    total_runpython = sum(len(v) for v in categorized.values())
    if total_runpython == 0:
        return "\n_no RunPython operations recorded_\n"

    # Wasted time = duration of every RunPython that is NOT "active".
    wasted_ms = sum(op["duration_ms"] for kind in ("inert", "read-only-empty") for op in categorized[kind])
    candidate_count = len(categorized["inert"]) + len(categorized["read-only-empty"])

    breakdown_rows = []
    descriptions = {
        "active": "ran INSERT/UPDATE/DELETE — real work",
        "read-only-empty": "ran only SELECTs, all <5ms total — looked for rows, found none",
        "read-only": "ran only SELECTs, ≥5ms total — may branch on results",
        "inert": "ran no SQL at all — pure no-op",
    }
    for kind in ("active", "read-only", "read-only-empty", "inert"):
        ops = categorized[kind]
        total = sum(op["duration_ms"] for op in ops)
        breakdown_rows.append([kind, len(ops), _fmt_ms(total), descriptions[kind]])

    breakdown_md = _md_table(["Class", "Count", "Total DB time", "Interpretation"], breakdown_rows)

    # Top candidates: inert + read-only-empty, sorted by duration desc to find
    # the slowest no-ops. Slowness here is the python-state rebuild around
    # nothing useful, so these are the highest-leverage to remove.
    candidates = [(op, kind) for kind in ("inert", "read-only-empty") for op in categorized[kind]]
    candidates.sort(key=lambda x: -x[0]["duration_ms"])

    candidate_rows = []
    for op, kind in candidates[:50]:
        callable_name = (op.get("metadata") or {}).get("callable", "?")
        candidate_rows.append(
            [
                op["database"],
                op["app_label"],
                op["migration_name"],
                kind,
                _fmt_ms(op["duration_ms"]),
                op.get("sql_count", 0),
                str(callable_name)[:60],
            ]
        )
    candidate_md = _md_table(
        ["DB", "App", "Migration", "Class", "Duration", "SQL count", "Callable"],
        candidate_rows,
    )

    lead = (
        f"\n**{candidate_count} of {total_runpython} RunPython operations** did nothing observable "
        f"to the database on this fresh-DB run, costing **{_fmt_ms(wasted_ms)}** in pure overhead. "
        "These are most likely 2-year-old data backfills / corruption fixes "
        "whose target rows never existed on a fresh database. Safest squash "
        "candidates after a per-migration audit.\n\n"
        "**Breakdown:**\n\n"
    )
    return lead + breakdown_md + "\n**Slowest no-op RunPython ops (top 50):**\n\n" + candidate_md


def _squash_clusters_section(runs: list[ProfileRun]) -> str:
    """Find runs of consecutive low-cost migrations per (db, app).

    Migrations sort lexically by name (Django's standard ``NNNN_description``
    prefix keeps this in real order). A cluster is a maximal sequence of
    migrations whose ``Migration.apply`` wall-clock is below
    ``CLUSTER_MAX_MS``. Output the largest clusters by size and by total cost.
    """
    CLUSTER_MAX_MS = 200.0
    MIN_CLUSTER_SIZE = 5

    # Build per-(db, app) ordered list of (name, apply_ms).
    by_app: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for run in runs:
        for (app, name), apply_ms in run.migration_summaries.items():
            by_app[(run.database, app)].append((name, apply_ms))

    clusters: list[tuple[str, str, str, str, int, float]] = []
    # (db, app, first_name, last_name, count, total_apply_ms)
    for (db, app), pairs in by_app.items():
        pairs.sort(key=lambda x: x[0])
        i = 0
        while i < len(pairs):
            if pairs[i][1] >= CLUSTER_MAX_MS:
                i += 1
                continue
            j = i
            total = 0.0
            while j < len(pairs) and pairs[j][1] < CLUSTER_MAX_MS:
                total += pairs[j][1]
                j += 1
            count = j - i
            if count >= MIN_CLUSTER_SIZE:
                clusters.append((db, app, pairs[i][0], pairs[j - 1][0], count, total))
            i = j

    if not clusters:
        return f"\n_no clusters of {MIN_CLUSTER_SIZE}+ consecutive low-cost migrations found_\n"

    clusters.sort(key=lambda c: -c[5])
    rows = []
    for db, app, first, last, count, total in clusters[:30]:
        # Optimistic ceiling savings if collapsed into one migration.
        saved = total * (count - 1) / count
        rows.append([db, app, first, last, count, _fmt_ms(total), _fmt_ms(saved)])

    lead = (
        f"\nA cluster is a run of {MIN_CLUSTER_SIZE}+ consecutive migrations in the same app, each "
        f"costing <{CLUSTER_MAX_MS:.0f}ms of `Migration.apply` wall-clock. These are the "
        "concrete batched-squash candidates — fold the range into one migration.\n\n"
    )
    return lead + _md_table(
        ["DB", "App", "From", "To", "Count", "Cluster total", "Est. savings if folded"],
        rows,
    )


def _squash_impact_section(runs: list[ProfileRun]) -> str:
    """Estimate the wall-clock you'd reclaim by folding low-SQL migrations.

    For each migration with ``SQL ≤ 10 ms``, treat the entire ``Migration.apply``
    cost as Python state-machine overhead — i.e. the work that would disappear
    if the operations had been folded into a neighbour. Group by app and
    aggregate. The per-migration overhead isn't a strict zero-after-squash
    floor (the inner ops still need to render state once), but the lion's
    share — the per-migration ``project_state.clone()`` + autodetector cost —
    collapses to ``1`` when N migrations become 1.
    """
    LOW_SQL_THRESHOLD_MS = 10.0

    # Group ops by (db, app, migration) so we can compute SQL totals quickly.
    sql_by_mig: dict[tuple[str, str, str], float] = defaultdict(float)
    for run in runs:
        for op in _effective_ops(run.ops):
            sql_by_mig[(run.database, op["app_label"], op["migration_name"])] += op["duration_ms"]

    per_app: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "apply_ms": 0.0, "sql_ms": 0.0})
    grand_total_apply_ms = 0.0
    grand_total_count = 0
    for run in runs:
        for (app, name), apply_ms in run.migration_summaries.items():
            sql_ms = sql_by_mig.get((run.database, app, name), 0.0)
            if sql_ms > LOW_SQL_THRESHOLD_MS:
                continue
            per_app[app]["count"] += 1
            per_app[app]["apply_ms"] += apply_ms
            per_app[app]["sql_ms"] += sql_ms
            grand_total_apply_ms += apply_ms
            grand_total_count += 1

    if grand_total_count == 0:
        return "\n_no low-SQL migrations found_\n"

    rows: list[list[Any]] = []
    for app, stats in sorted(per_app.items(), key=lambda x: -x[1]["apply_ms"]):
        n = int(stats["count"])
        apply_ms = stats["apply_ms"]
        avg = apply_ms / n if n else 0.0
        # Optimistic ceiling: collapse N low-SQL migrations into 1, you keep
        # the SQL but pay state cost once — i.e. save (N-1)/N of the apply
        # cost. Assumes uniform-ish per-migration cost, which is roughly
        # true for the no-op cluster (state.clone dominates).
        upper_savings_ms = apply_ms * (n - 1) / n if n > 0 else 0.0
        rows.append([app, n, _fmt_ms(apply_ms), _fmt_ms(avg), _fmt_ms(upper_savings_ms)])

    lead = (
        f"\nFound **{grand_total_count} migrations** with ≤{LOW_SQL_THRESHOLD_MS:.0f}ms of SQL "
        f"work, totalling {_fmt_ms(grand_total_apply_ms)} of `Migration.apply` time. "
        "These are the ones where the cost is almost entirely Python — i.e. "
        "the strongest squash ROI.\n\n"
        "**Estimated savings** assumes folding N low-SQL migrations into 1 "
        "trims `(N-1)/N` of their apply time (state-machine overhead collapses to one pass).\n\n"
    )
    return lead + _md_table(
        ["App", "Low-SQL migrations", "Apply total", "Avg per migration", "Est. savings if folded"],
        rows,
    )


def _heavy_migrations(ops: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    by_mig: dict[tuple[str, str, str], float] = defaultdict(float)
    for op in ops:
        by_mig[(op["database"], op["app_label"], op["migration_name"])] += op["duration_ms"]
    totals = sorted(by_mig.values(), reverse=True)
    if not totals:
        return ["DB", "App", "Migration", "Duration"], []
    cutoff = _percentile(totals, P95)
    heavy = [(key, total) for key, total in by_mig.items() if total >= cutoff]
    heavy.sort(key=lambda x: -x[1])
    rows = [[k[0], k[1], k[2], _fmt_ms(total)] for k, total in heavy]
    return ["DB", "App", "Migration", "Duration"], rows
