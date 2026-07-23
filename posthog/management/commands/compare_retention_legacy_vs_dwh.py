"""Compare the legacy vs new ("DWH variant") retention fixed-interval base query.

Runs every affected RetentionQuery insight twice — once with the variant toggle forced OFF
(legacy) and once ON (new) — diffs the results for correctness and benchmarks performance
with an interleaved, multi-iteration protocol plus load-independent ClickHouse resource stats
read back from the query log. Emits a self-contained, LLM-pasteable Markdown report so any
regression can be handed to another model to fix.

The toggle lives in
``posthog.hogql_queries.insights.retention.retention_base_query_fixed.retention_fixed_interval_base_query_use_dwh_variant``
and is forced via ``unittest.mock.patch`` (the patch target is the shared
``RETENTION_BASE_QUERY_VARIANT_PATCH_PATH`` constant). Two insight shapes are NOT affected by the
toggle and are classified SKIPPED: data-warehouse retention (always routed to the new path) and
the 24h rolling window mode (a different builder with no legacy/new split).

This command is strictly read-only: it never saves or mutates insights.

Examples:
    # Local: a single insight, light perf, default system.query_log resource stats
    python manage.py compare_retention_legacy_vs_dwh --insight-id 1234 --perf-iterations 3

    # All retention insights for a team, correctness only
    python manage.py compare_retention_legacy_vs_dwh --team-id 42 --no-perf

    # Production (multi-node): read resource stats from the distributed archive table
    python manage.py compare_retention_legacy_vs_dwh --limit 200 \\
        --query-log-table query_log_archive --no-flush-query-log --query-log-wait 90
"""

import re
import json
import time
import uuid
import argparse
import traceback
import statistics
import dataclasses
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from copy import deepcopy
from time import perf_counter
from typing import Any, Optional

from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError

from posthog.schema import HogQLQueryModifiers, RetentionResult

from posthog.hogql.modifiers import create_default_modifiers_for_team

import posthog.clickhouse.client.execute as ch_execute
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.insights.retention.retention_base_query_fixed import (
    RETENTION_FIXED_INTERVAL_BASE_QUERY_DWH_VARIANT_FLAG,
)
from posthog.hogql_queries.insights.retention.test.retention_base_query_variant import (
    RETENTION_BASE_QUERY_VARIANT_PATCH_PATH,
)
from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.query_runner import get_query_runner

from products.product_analytics.backend.models.insight import Insight

DATA_WAREHOUSE_ENTITY_TYPE = "data_warehouse"
ROLLING_24H_WINDOW_MODE = "24_hour_windows"
CLICKHOUSE_EXECUTE_TIMING_KEY = "clickhouse_execute"
DEFAULT_MAX_CELL_DIFFS = 25
DEFAULT_WORST_N = 15
_SAFE_TABLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")


# --------------------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------------------


@dataclasses.dataclass
class VariantRun:
    results: list[RetentionResult]
    hogql: Optional[str]
    wall_s: float
    ch_s: float
    query_ids: list[str]


@dataclasses.dataclass
class CellDiff:
    breakdown_value: Any
    row_label: str
    value_label: Optional[str]
    field: str  # "count" | "aggregation_value"
    legacy: float
    dwh: float
    abs_diff: float
    rel_diff: Optional[float]  # None when legacy == 0


@dataclasses.dataclass
class CorrectnessDiff:
    status: str  # "OK" | "MISMATCH"
    row_count_legacy: int
    row_count_dwh: int
    breakdown_keys_legacy: list[Any]
    breakdown_keys_dwh: list[Any]
    breakdown_only_legacy: list[Any]
    breakdown_only_dwh: list[Any]
    other_bucket_changed: bool
    cell_diffs: list[CellDiff]
    notes: list[str]


@dataclasses.dataclass
class VariantTiming:
    samples_ms: list[float]
    min_ms: float
    median_ms: float
    p95_ms: float
    stdev_ms: float


@dataclasses.dataclass
class ResourceStats:
    read_bytes: int
    read_rows: int
    memory_usage: int
    query_duration_ms: int
    ch_query_count: int


@dataclasses.dataclass
class PerfResult:
    wall_legacy: VariantTiming
    wall_dwh: VariantTiming
    ch_legacy: VariantTiming
    ch_dwh: VariantTiming
    ratio_median_wall: Optional[float]
    ratio_min_wall: Optional[float]
    ratio_median_ch: Optional[float]
    delta_median_wall_ms: float
    is_regression: bool
    is_improvement: bool


@dataclasses.dataclass
class InsightFinding:
    insight_id: int
    short_id: str
    team_id: int
    name: str
    url: str
    status: str  # "OK" | "MISMATCH" | "ERROR" | "SKIPPED"
    has_breakdown: bool = False
    skip_reason: Optional[str] = None
    error_type: Optional[str] = None
    error_detail: Optional[str] = None
    source_json: Optional[str] = None
    correctness: Optional[CorrectnessDiff] = None
    legacy_hogql: Optional[str] = None
    dwh_hogql: Optional[str] = None
    perf: Optional[PerfResult] = None
    resource_legacy: Optional[ResourceStats] = None
    resource_dwh: Optional[ResourceStats] = None
    legacy_query_ids: list[str] = dataclasses.field(default_factory=list)
    dwh_query_ids: list[str] = dataclasses.field(default_factory=list)
    bytes_ratio: Optional[float] = None


@dataclasses.dataclass
class PerfAggregate:
    n_compared: int
    wall_ratio_dist: dict[str, float]
    bytes_ratio_dist: dict[str, float]
    n_regressions: int
    n_improvements: int
    regressions: list[InsightFinding]
    improvements: list[InsightFinding]
    worst_by_rel: list[InsightFinding]
    worst_by_abs: list[InsightFinding]
    worst_by_bytes: list[InsightFinding]


# --------------------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB / ClickHouse)
# --------------------------------------------------------------------------------------


def _attr(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def classify_insight(insight: Insight) -> tuple[str, str]:
    """Return ("compare"|"skip"|"error", reason) without executing anything."""
    query = insight.query
    if not isinstance(query, dict):
        return ("error", "insight.query is not a dict")
    source = query.get("source")
    if not isinstance(source, dict) or source.get("kind") != "RetentionQuery":
        return ("error", "query.source is not a RetentionQuery")
    retention_filter = source.get("retentionFilter")
    if not isinstance(retention_filter, dict):
        return ("error", "RetentionQuery has no retentionFilter")
    if retention_filter.get("timeWindowMode") == ROLLING_24H_WINDOW_MODE:
        return ("skip", "24h rolling window (toggle has no effect)")
    for entity_key in ("targetEntity", "returningEntity"):
        entity = retention_filter.get(entity_key)
        if isinstance(entity, dict) and entity.get("type") == DATA_WAREHOUSE_ENTITY_TYPE:
            return ("skip", "data_warehouse (new-path only)")
    return ("compare", "")


def _clickhouse_seconds(timings: Optional[Sequence[Any]]) -> float:
    """Sum the seconds of every timing entry whose leaf key is ``clickhouse_execute``.

    Timing keys are hierarchical (e.g. ``./retention_query/.../clickhouse_execute``); a single
    ``.calculate()`` can issue several ClickHouse queries, so we sum rather than take the first.
    """
    if not timings:
        return 0.0
    total = 0.0
    for timing in timings:
        key = _attr(timing, "k") or ""
        if key.split("/")[-1] == CLICKHOUSE_EXECUTE_TIMING_KEY:
            total += float(_attr(timing, "t") or 0.0)
    return total


def _within(legacy: float, dwh: float, tol_abs: float, tol_rel: float) -> bool:
    if legacy == dwh:
        return True
    diff = abs(legacy - dwh)
    if diff <= tol_abs:
        return True
    return legacy != 0 and diff / abs(legacy) <= tol_rel


def _rel_diff(legacy: float, dwh: float) -> Optional[float]:
    if legacy == 0:
        return None
    return (dwh - legacy) / abs(legacy)


def _breakdown_values_in_order(results: Sequence[Any]) -> list[Any]:
    ordered: list[Any] = []
    for result in results:
        breakdown_value = _attr(result, "breakdown_value")
        if breakdown_value not in ordered:
            ordered.append(breakdown_value)
    return ordered


def diff_retention_results(
    legacy: Sequence[Any],
    dwh: Sequence[Any],
    *,
    count_tol_abs: float = 0.0,
    count_tol_rel: float = 0.0,
    agg_tol_rel: float = 1e-6,
) -> CorrectnessDiff:
    """Diff two retention result sets, keyed by (breakdown_value, row label).

    ``format_results`` is shared between the legacy and new SQL paths, so the row/label structure
    is expected to be identical; the only legitimate differences are numeric counts/aggregation
    values. A large enough count delta, however, can change which breakdown values get ranked into
    the "Other" bucket — hence the breakdown-set and Other-bucket checks.
    """
    legacy_by_key = {(_attr(r, "breakdown_value"), _attr(r, "label")): r for r in legacy}
    dwh_by_key = {(_attr(r, "breakdown_value"), _attr(r, "label")): r for r in dwh}

    breakdowns_legacy = _breakdown_values_in_order(legacy)
    breakdowns_dwh = _breakdown_values_in_order(dwh)
    set_legacy, set_dwh = set(breakdowns_legacy), set(breakdowns_dwh)
    only_legacy = [b for b in breakdowns_legacy if b not in set_dwh]
    only_dwh = [b for b in breakdowns_dwh if b not in set_legacy]
    other_bucket_changed = (BREAKDOWN_OTHER_STRING_LABEL in set_legacy) != (BREAKDOWN_OTHER_STRING_LABEL in set_dwh)

    cell_diffs: list[CellDiff] = []
    notes: list[str] = []
    # Row keys should be identical between variants (format_results is shared); flag — never
    # silently drop — any that aren't, so an OK verdict can't mask differing row coverage.
    rows_only_legacy = [k for k in legacy_by_key if k not in dwh_by_key]
    rows_only_dwh = [k for k in dwh_by_key if k not in legacy_by_key]
    for key in rows_only_legacy:
        notes.append(f"row (breakdown={key[0]!r}, label={key[1]!r}) present in legacy but missing in DWH")
    for key in rows_only_dwh:
        notes.append(f"row (breakdown={key[0]!r}, label={key[1]!r}) present in DWH but missing in legacy")
    for key in legacy_by_key:
        if key not in dwh_by_key:
            continue
        legacy_values = _attr(legacy_by_key[key], "values") or []
        dwh_values = _attr(dwh_by_key[key], "values") or []
        dwh_by_label = {_attr(v, "label"): v for v in dwh_values}
        for legacy_value in legacy_values:
            value_label = _attr(legacy_value, "label")
            dwh_value = dwh_by_label.get(value_label)
            if dwh_value is None:
                notes.append(f"value label {value_label!r} missing in DWH for {key}")
                continue
            legacy_count = float(_attr(legacy_value, "count") or 0.0)
            dwh_count = float(_attr(dwh_value, "count") or 0.0)
            if not _within(legacy_count, dwh_count, count_tol_abs, count_tol_rel):
                cell_diffs.append(
                    CellDiff(
                        breakdown_value=key[0],
                        row_label=key[1],
                        value_label=value_label,
                        field="count",
                        legacy=legacy_count,
                        dwh=dwh_count,
                        abs_diff=abs(legacy_count - dwh_count),
                        rel_diff=_rel_diff(legacy_count, dwh_count),
                    )
                )
            legacy_agg = _attr(legacy_value, "aggregation_value")
            dwh_agg = _attr(dwh_value, "aggregation_value")
            if legacy_agg is not None or dwh_agg is not None:
                legacy_agg_f = float(legacy_agg or 0.0)
                dwh_agg_f = float(dwh_agg or 0.0)
                if not _within(legacy_agg_f, dwh_agg_f, 0.0, agg_tol_rel):
                    cell_diffs.append(
                        CellDiff(
                            breakdown_value=key[0],
                            row_label=key[1],
                            value_label=value_label,
                            field="aggregation_value",
                            legacy=legacy_agg_f,
                            dwh=dwh_agg_f,
                            abs_diff=abs(legacy_agg_f - dwh_agg_f),
                            rel_diff=_rel_diff(legacy_agg_f, dwh_agg_f),
                        )
                    )

    cell_diffs.sort(key=lambda c: c.abs_diff, reverse=True)
    is_mismatch = (
        len(legacy) != len(dwh)
        or bool(only_legacy)
        or bool(only_dwh)
        or bool(rows_only_legacy)
        or bool(rows_only_dwh)
        or bool(cell_diffs)
    )
    return CorrectnessDiff(
        status="MISMATCH" if is_mismatch else "OK",
        row_count_legacy=len(legacy),
        row_count_dwh=len(dwh),
        breakdown_keys_legacy=breakdowns_legacy,
        breakdown_keys_dwh=breakdowns_dwh,
        breakdown_only_legacy=only_legacy,
        breakdown_only_dwh=only_dwh,
        other_bucket_changed=other_bucket_changed,
        cell_diffs=cell_diffs,
        notes=notes,
    )


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def summarize_samples(samples_ms: list[float]) -> VariantTiming:
    if not samples_ms:
        return VariantTiming(samples_ms=[], min_ms=0.0, median_ms=0.0, p95_ms=0.0, stdev_ms=0.0)
    ordered = sorted(samples_ms)
    return VariantTiming(
        samples_ms=list(samples_ms),
        min_ms=ordered[0],
        median_ms=statistics.median(ordered),
        p95_ms=_percentile(ordered, 95),
        stdev_ms=statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
    )


def compute_perf_result(
    wall_legacy: list[float],
    wall_dwh: list[float],
    ch_legacy: list[float],
    ch_dwh: list[float],
    *,
    regression_rel: float,
    regression_ms: float,
) -> PerfResult:
    wl = summarize_samples(wall_legacy)
    wd = summarize_samples(wall_dwh)
    cl = summarize_samples(ch_legacy)
    cd = summarize_samples(ch_dwh)

    ratio_median_wall = wd.median_ms / wl.median_ms if wl.median_ms > 0 else None
    ratio_min_wall = wd.min_ms / wl.min_ms if wl.min_ms > 0 else None
    ratio_median_ch = cd.median_ms / cl.median_ms if cl.median_ms > 0 else None
    delta_median_wall_ms = wd.median_ms - wl.median_ms

    # A regression needs BOTH a relative slowdown beyond the threshold AND a meaningful absolute
    # delta — the ms floor keeps noise on tiny queries from masquerading as regressions.
    is_regression = (
        ratio_median_wall is not None
        and (ratio_median_wall - 1) > regression_rel
        and delta_median_wall_ms > regression_ms
    )
    is_improvement = (
        ratio_median_wall is not None
        and (1 - ratio_median_wall) > regression_rel
        and (-delta_median_wall_ms) > regression_ms
    )
    return PerfResult(
        wall_legacy=wl,
        wall_dwh=wd,
        ch_legacy=cl,
        ch_dwh=cd,
        ratio_median_wall=ratio_median_wall,
        ratio_min_wall=ratio_min_wall,
        ratio_median_ch=ratio_median_ch,
        delta_median_wall_ms=delta_median_wall_ms,
        is_regression=is_regression,
        is_improvement=is_improvement,
    )


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "n": float(len(ordered)),
        "min": ordered[0],
        "p25": _percentile(ordered, 25),
        "median": _percentile(ordered, 50),
        "p75": _percentile(ordered, 75),
        "p90": _percentile(ordered, 90),
        "max": ordered[-1],
    }


def parse_query_log_rows(rows: Sequence[Sequence[Any]]) -> dict[str, ResourceStats]:
    """Turn raw query-log aggregate rows into a {query_id: ResourceStats} map."""
    stats: dict[str, ResourceStats] = {}
    for row in rows:
        stats[row[0]] = ResourceStats(
            read_bytes=int(row[1] or 0),
            read_rows=int(row[2] or 0),
            memory_usage=int(row[3] or 0),
            query_duration_ms=int(row[4] or 0),
            ch_query_count=int(row[5] or 0),
        )
    return stats


def aggregate_resource_stats(
    query_ids: Sequence[str], stats_by_id: dict[str, ResourceStats]
) -> Optional[ResourceStats]:
    matched = [stats_by_id[q] for q in query_ids if q in stats_by_id]
    if not matched:
        return None
    return ResourceStats(
        read_bytes=sum(s.read_bytes for s in matched),
        read_rows=sum(s.read_rows for s in matched),
        memory_usage=max(s.memory_usage for s in matched),
        query_duration_ms=sum(s.query_duration_ms for s in matched),
        ch_query_count=sum(s.ch_query_count for s in matched),
    )


def _wall_ratio_key(finding: InsightFinding) -> float:
    if finding.perf is None or finding.perf.ratio_median_wall is None:
        return 0.0
    return finding.perf.ratio_median_wall


def _delta_key(finding: InsightFinding) -> float:
    return finding.perf.delta_median_wall_ms if finding.perf else 0.0


def _bytes_ratio_key(finding: InsightFinding) -> float:
    return finding.bytes_ratio if finding.bytes_ratio is not None else 0.0


def build_perf_aggregate(findings: list[InsightFinding], *, worst_n: int) -> PerfAggregate:
    compared = [f for f in findings if f.perf is not None]
    wall_ratios = [f.perf.ratio_median_wall for f in compared if f.perf and f.perf.ratio_median_wall]
    bytes_ratios = [f.bytes_ratio for f in compared if f.bytes_ratio]
    regressions = [f for f in compared if f.perf and f.perf.is_regression]
    improvements = [f for f in compared if f.perf and f.perf.is_improvement]
    with_ratio = [f for f in compared if f.perf and f.perf.ratio_median_wall is not None]
    with_bytes = [f for f in compared if f.bytes_ratio is not None]
    return PerfAggregate(
        n_compared=len(compared),
        wall_ratio_dist=_distribution(wall_ratios),
        bytes_ratio_dist=_distribution(bytes_ratios),
        n_regressions=len(regressions),
        n_improvements=len(improvements),
        regressions=sorted(regressions, key=_wall_ratio_key, reverse=True),
        improvements=sorted(improvements, key=_wall_ratio_key),
        worst_by_rel=sorted(with_ratio, key=_wall_ratio_key, reverse=True)[:worst_n],
        worst_by_abs=sorted(compared, key=_delta_key, reverse=True)[:worst_n],
        worst_by_bytes=sorted(with_bytes, key=_bytes_ratio_key, reverse=True)[:worst_n],
    )


# --------------------------------------------------------------------------------------
# Execution (touches the query runner + ClickHouse)
# --------------------------------------------------------------------------------------


def run_variant(
    insight: Insight,
    use_dwh: bool,
    modifiers: HogQLQueryModifiers,
    *,
    marker: Optional[str] = None,
    capture_query_ids: bool = False,
) -> VariantRun:
    """Execute one retention variant. Read-only: deepcopies the query, scopes the patch."""
    query = insight.query
    if not isinstance(query, dict):
        raise ValueError(f"insight {insight.id} has a non-dict query")
    source = deepcopy(query["source"])
    if marker:
        # The query_id ClickHouse records becomes f"{team_id}_{client_query_id}_{random}", so the
        # marker makes captured query_ids self-describing in the report. Setting client_query_id
        # requires team_id in the tags as well.
        tag_queries(client_query_id=marker, team_id=insight.team_id)

    captured: list[str] = []
    real_validated_client_query_id = ch_execute.validated_client_query_id

    def _capture() -> Optional[str]:
        query_id = real_validated_client_query_id()
        if query_id is not None:
            captured.append(query_id)
        return query_id

    capture_ctx = (
        patch.object(ch_execute, "validated_client_query_id", side_effect=_capture)
        if capture_query_ids
        else nullcontext()
    )
    try:
        with patch(RETENTION_BASE_QUERY_VARIANT_PATCH_PATH, return_value=use_dwh), capture_ctx:
            start = perf_counter()
            response = get_query_runner(source, insight.team, modifiers=deepcopy(modifiers)).calculate()
            wall_s = perf_counter() - start
    finally:
        if marker:
            # Clear the marker so later perf-only iterations don't tag their query-log rows with it.
            tag_queries(client_query_id=None)

    return VariantRun(
        results=response.results or [],
        hogql=response.hogql,
        wall_s=wall_s,
        ch_s=_clickhouse_seconds(response.timings),
        query_ids=captured,
    )


def fetch_query_log_stats(
    query_ids: Sequence[str],
    *,
    table: str,
    flush: bool,
    wait_seconds: float,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, ResourceStats]:
    """Read per-query resource stats from the query log, polling until rows appear.

    Degrades gracefully: any failure (missing table, no privileges, lag) returns whatever was
    found so far so the run continues with timing-only stats.
    """
    unique_ids = list(dict.fromkeys(query_ids))
    if not unique_ids:
        return {}
    if not _SAFE_TABLE_RE.match(table):
        raise CommandError(f"Unsafe --query-log-table value: {table!r}")

    def _emit(message: str) -> None:
        if log:
            log(message)

    if flush:
        try:
            sync_execute("SYSTEM FLUSH LOGS")
        except Exception as exc:
            _emit(f"SYSTEM FLUSH LOGS failed ({exc}); continuing without it")

    # is_initial_query = 1 keeps distributed sub-query rows from double-counting read_bytes on a
    # multi-node cluster; on a single node it simply selects the one row per ClickHouse query.
    query = f"""
        SELECT
            query_id,
            sum(read_bytes),
            sum(read_rows),
            max(memory_usage),
            sum(query_duration_ms),
            count()
        FROM {table}
        WHERE query_id IN %(query_ids)s
          AND type IN ('QueryFinish', 'ExceptionWhileProcessing')
          AND is_initial_query = 1
        GROUP BY query_id
    """  # noqa: S608 — table is operator-supplied and validated against _SAFE_TABLE_RE above

    deadline = perf_counter() + max(0.0, wait_seconds)
    found: dict[str, ResourceStats] = {}
    while True:
        try:
            rows = sync_execute(query, {"query_ids": unique_ids})
        except Exception as exc:
            _emit(f"query_log lookup failed on {table} ({exc}); continuing with timing only")
            return found
        found = parse_query_log_rows(rows)
        if len(found) >= len(unique_ids) or perf_counter() >= deadline:
            break
        time.sleep(1.0)
    if len(found) < len(unique_ids):
        _emit(f"query_log: matched {len(found)}/{len(unique_ids)} query_ids on {table} (some stats omitted)")
    return found


# --------------------------------------------------------------------------------------
# Formatting / report
# --------------------------------------------------------------------------------------


def _trim(text: Optional[str], max_chars: int) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n… (trimmed, {len(text) - max_chars} more chars)"


def _fmt_ms(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}ms" if value < 1000 else f"{value / 1000:.2f}s"


def _fmt_bytes(num: Optional[int]) -> str:
    if num is None:
        return "n/a"
    size = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{int(size)}B" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TiB"


def _fmt_ratio(ratio: Optional[float]) -> str:
    if ratio is None:
        return "n/a"
    pct = (ratio - 1) * 100
    sign = "+" if pct >= 0 else ""
    return f"{ratio:.2f}× ({sign}{pct:.0f}%)"


def _fmt_breakdown(value: Any) -> str:
    if value is None:
        return "—"
    return str(value)


def _verdict(ratio: Optional[float]) -> str:
    if ratio is None:
        return "n/a"
    if ratio > 1.05:
        return "slower"
    if ratio < 0.95:
        return "faster"
    return "~even"


def render_markdown_report(
    findings: list[InsightFinding],
    aggregate: PerfAggregate,
    run_meta: dict[str, Any],
) -> str:
    counts = run_meta["counts"]
    lines: list[str] = []
    out = lines.append

    out("# Retention legacy vs DWH-variant comparison\n")
    out(f"- Generated: {run_meta['timestamp']}")
    out(f"- Feature flag: `{RETENTION_FIXED_INTERVAL_BASE_QUERY_DWH_VARIANT_FLAG}`")
    out(f"- Patch target: `{RETENTION_BASE_QUERY_VARIANT_PATCH_PATH}`")
    out(f"- Args: `{run_meta['args']}`\n")
    out(
        "> **Reading the perf numbers.** `.calculate()` bypasses PostHog's result cache, but "
        "ClickHouse's own mark/page cache still warms across the interleaved runs, so absolute "
        "millisecond values reflect a warm cache and run faster than a cold production first-hit. "
        "Trust the **ratios** and **read_bytes** (load-independent); treat absolute ms as "
        "indicative. Interleaving legacy/new and reporting median + min (not mean) cancels "
        "asymmetric cache warming and one-off spikes.\n"
    )

    out("## Summary\n")
    out("| Result | Count |")
    out("| --- | --- |")
    out(f"| Compared | {counts['compared']} |")
    out(f"| ✅ OK | {counts['ok']} |")
    out(f"| ❌ MISMATCH | {counts['mismatch']} |")
    out(f"| ⚠️ ERROR | {counts['error']} |")
    out(f"| ⏭️ SKIPPED | {counts['skipped']} |")
    out("")
    if aggregate.n_compared:
        wall_median = aggregate.wall_ratio_dist.get("median")
        bytes_median = aggregate.bytes_ratio_dist.get("median")
        out(
            f"Performance: median wall ratio **{_fmt_ratio(wall_median)}** ({_verdict(wall_median)}), "
            f"median bytes ratio **{_fmt_ratio(bytes_median)}**, "
            f"**{aggregate.n_regressions}** regressions / **{aggregate.n_improvements}** improvements "
            f"(threshold: > {run_meta['regression_rel'] * 100:.0f}% and "
            f"> {run_meta['regression_ms']:.0f}ms slower).\n"
        )

    _render_perf_distribution(out, aggregate)
    _render_mismatches(out, findings, run_meta)
    _render_regressions(out, aggregate.regressions, run_meta)
    _render_errors(out, [f for f in findings if f.status == "ERROR"])
    _render_skipped(out, [f for f in findings if f.status == "SKIPPED"])

    return "\n".join(lines) + "\n"


def _render_perf_distribution(out: Callable[[str], None], aggregate: PerfAggregate) -> None:
    if not aggregate.n_compared:
        return
    out("## Performance distribution\n")
    out("Distribution of the per-insight median ratio (DWH ÷ legacy) across all compared insights.")
    out("A single timing is dominated by per-query variance; the distribution cancels that noise")
    out("and exposes the tail (the few insights that regress even when the median is fine).\n")

    def dist_row(label: str, dist: dict[str, float]) -> str:
        if not dist:
            return f"| {label} | n/a | n/a | n/a | n/a | n/a | n/a |"
        return (
            f"| {label} | {dist['min']:.2f}× | {dist['p25']:.2f}× | {dist['median']:.2f}× | "
            f"{dist['p75']:.2f}× | {dist['p90']:.2f}× | {dist['max']:.2f}× |"
        )

    out("| Metric | min | p25 | median | p75 | p90 | max |")
    out("| --- | --- | --- | --- | --- | --- | --- |")
    out(dist_row("Wall time", aggregate.wall_ratio_dist))
    out(dist_row("Bytes read", aggregate.bytes_ratio_dist))
    out("")

    if aggregate.worst_by_rel:
        out("### Worst by relative slowdown\n")
        _render_worst_table(out, aggregate.worst_by_rel)
    if aggregate.worst_by_abs:
        out("### Worst by absolute slowdown (ms)\n")
        _render_worst_table(out, aggregate.worst_by_abs)
    if aggregate.worst_by_bytes:
        out("### Worst by bytes read\n")
        _render_worst_table(out, aggregate.worst_by_bytes, show_bytes=True)


def _render_worst_table(
    out: Callable[[str], None], findings: list[InsightFinding], *, show_bytes: bool = False
) -> None:
    if show_bytes:
        out("| Insight | Wall ratio | Legacy bytes | DWH bytes | Bytes ratio |")
        out("| --- | --- | --- | --- | --- |")
        for f in findings:
            legacy_bytes = f.resource_legacy.read_bytes if f.resource_legacy else None
            dwh_bytes = f.resource_dwh.read_bytes if f.resource_dwh else None
            ratio = f.perf.ratio_median_wall if f.perf else None
            out(
                f"| [{f.short_id}]({f.url}) | {_fmt_ratio(ratio)} | {_fmt_bytes(legacy_bytes)} | "
                f"{_fmt_bytes(dwh_bytes)} | {_fmt_ratio(f.bytes_ratio)} |"
            )
        out("")
        return
    out("| Insight | Legacy median | DWH median | Wall ratio | Δ median |")
    out("| --- | --- | --- | --- | --- |")
    for f in findings:
        if not f.perf:
            continue
        out(
            f"| [{f.short_id}]({f.url}) | {_fmt_ms(f.perf.wall_legacy.median_ms)} | "
            f"{_fmt_ms(f.perf.wall_dwh.median_ms)} | {_fmt_ratio(f.perf.ratio_median_wall)} | "
            f"{f.perf.delta_median_wall_ms:+.1f}ms |"
        )
    out("")


def _render_finding_header(out: Callable[[str], None], f: InsightFinding, title: str) -> None:
    out(f"### {title} — insight {f.insight_id} (`{f.short_id}`), team {f.team_id}\n")
    if f.name:
        out(f"- Name: {f.name}")
    out(f"- URL: {f.url}")
    out(f"- Has breakdown: {'yes' if f.has_breakdown else 'no'}\n")


def _render_source_and_hogql(out: Callable[[str], None], f: InsightFinding) -> None:
    if f.source_json:
        out("**RetentionQuery source:**\n")
        out("```json")
        out(f.source_json)
        out("```\n")
    if f.legacy_hogql:
        out("**Generated HogQL — LEGACY:**\n")
        out("```sql")
        out(f.legacy_hogql)
        out("```\n")
    if f.dwh_hogql:
        out("**Generated HogQL — DWH:**\n")
        out("```sql")
        out(f.dwh_hogql)
        out("```\n")


def _render_mismatches(out: Callable[[str], None], findings: list[InsightFinding], run_meta: dict[str, Any]) -> None:
    mismatches = [f for f in findings if f.status == "MISMATCH"]
    if not mismatches:
        return
    out("## Correctness mismatches\n")
    out("Each block is self-contained — paste one into an LLM to diagnose that regression.\n")
    # Non-breakdown first (more surprising); breakdowns are a declared known parity gap.
    ordered = sorted(mismatches, key=lambda f: f.has_breakdown)
    for f in ordered:
        diff = f.correctness
        _render_finding_header(out, f, "MISMATCH")
        if diff is not None:
            if diff.row_count_legacy != diff.row_count_dwh:
                out(f"- Row count differs: legacy={diff.row_count_legacy}, dwh={diff.row_count_dwh}")
            if diff.breakdown_only_legacy:
                out(f"- Breakdown values only in legacy: {[_fmt_breakdown(b) for b in diff.breakdown_only_legacy]}")
            if diff.breakdown_only_dwh:
                out(f"- Breakdown values only in dwh: {[_fmt_breakdown(b) for b in diff.breakdown_only_dwh]}")
            if diff.other_bucket_changed:
                out("- ⚠️ 'Other' bucket membership changed between variants (breakdown ranking diverged)")
            if diff.cell_diffs:
                out(f"- {len(diff.cell_diffs)} differing cell(s)\n")
                _render_cell_diff_table(out, diff.cell_diffs, run_meta["max_cell_diffs"])
            for note in diff.notes[:10]:
                out(f"- Note: {note}")
            out("")
        _render_source_and_hogql(out, f)


def _render_cell_diff_table(out: Callable[[str], None], cell_diffs: list[CellDiff], max_rows: int) -> None:
    out("| Breakdown | Cohort | Period | Field | Legacy | DWH | Δabs | Δrel |")
    out("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for diff in cell_diffs[:max_rows]:
        rel = "n/a" if diff.rel_diff is None else f"{diff.rel_diff * 100:+.1f}%"
        out(
            f"| {_fmt_breakdown(diff.breakdown_value)} | {diff.row_label} | {diff.value_label} | "
            f"{diff.field} | {diff.legacy:g} | {diff.dwh:g} | {diff.abs_diff:g} | {rel} |"
        )
    if len(cell_diffs) > max_rows:
        out(f"| … | | | | | | +{len(cell_diffs) - max_rows} more | |")
    out("")


def _render_regressions(
    out: Callable[[str], None], regressions: list[InsightFinding], run_meta: dict[str, Any]
) -> None:
    if not regressions:
        return
    out("## Performance regressions\n")
    for f in regressions:
        _render_finding_header(out, f, "REGRESSION")
        if f.perf:
            _render_perf_table(out, f)
        _render_source_and_hogql(out, f)


def _render_perf_table(out: Callable[[str], None], f: InsightFinding) -> None:
    perf = f.perf
    assert perf is not None
    out(
        f"- Wall ratio (median): **{_fmt_ratio(perf.ratio_median_wall)}**, "
        f"min: {_fmt_ratio(perf.ratio_min_wall)}, "
        f"ClickHouse-execute ratio: {_fmt_ratio(perf.ratio_median_ch)}, "
        f"Δ median: {perf.delta_median_wall_ms:+.1f}ms"
    )
    if f.bytes_ratio is not None:
        out(f"- Bytes read ratio: **{_fmt_ratio(f.bytes_ratio)}**")
    out("")
    out("| Metric | Legacy | DWH |")
    out("| --- | --- | --- |")
    out(f"| Wall median | {_fmt_ms(perf.wall_legacy.median_ms)} | {_fmt_ms(perf.wall_dwh.median_ms)} |")
    out(f"| Wall min | {_fmt_ms(perf.wall_legacy.min_ms)} | {_fmt_ms(perf.wall_dwh.min_ms)} |")
    out(f"| Wall p95 | {_fmt_ms(perf.wall_legacy.p95_ms)} | {_fmt_ms(perf.wall_dwh.p95_ms)} |")
    out(f"| CH median | {_fmt_ms(perf.ch_legacy.median_ms)} | {_fmt_ms(perf.ch_dwh.median_ms)} |")
    if f.resource_legacy and f.resource_dwh:
        out(f"| Read bytes | {_fmt_bytes(f.resource_legacy.read_bytes)} | {_fmt_bytes(f.resource_dwh.read_bytes)} |")
        out(f"| Read rows | {f.resource_legacy.read_rows:,} | {f.resource_dwh.read_rows:,} |")
        out(
            f"| Peak memory | {_fmt_bytes(f.resource_legacy.memory_usage)} | {_fmt_bytes(f.resource_dwh.memory_usage)} |"
        )
    out("")


def _render_errors(out: Callable[[str], None], errors: list[InsightFinding]) -> None:
    if not errors:
        return
    out("## Errors\n")
    for f in errors:
        _render_finding_header(out, f, "ERROR")
        out(f"- Error: `{f.error_type}`")
        if f.error_detail:
            out("```")
            out(f.error_detail)
            out("```\n")
        if f.source_json:
            out("```json")
            out(f.source_json)
            out("```\n")


def _render_skipped(out: Callable[[str], None], skipped: list[InsightFinding]) -> None:
    if not skipped:
        return
    out("## Skipped\n")
    out("| Insight | Team | Reason |")
    out("| --- | --- | --- |")
    for f in skipped:
        out(f"| [{f.short_id}]({f.url}) | {f.team_id} | {f.skip_reason} |")
    out("")


# --------------------------------------------------------------------------------------
# Command
# --------------------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Compare legacy vs new (DWH variant) retention insights for correctness and performance"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Restrict to team id(s); repeatable")
        parser.add_argument("--insight-id", type=int, action="append", help="Restrict to insight DB id(s); repeatable")
        parser.add_argument("--short-id", type=str, action="append", help="Restrict to insight short_id(s); repeatable")
        parser.add_argument("--limit", type=int, default=100, help="Max insights to process (default 100)")
        parser.add_argument("--sample", type=int, default=None, help="Randomly sample N insights instead of by date")
        parser.add_argument("--perf-iterations", type=int, default=5, help="Interleaved timing iterations per variant")
        parser.add_argument("--warmup", action="store_true", help="Run one discarded warmup per variant first")
        parser.add_argument("--no-perf", action="store_true", help="Correctness only; skip timing and resource stats")
        parser.add_argument("--count-tolerance-abs", type=float, default=0.0, help="Absolute count tolerance")
        parser.add_argument(
            "--count-tolerance-rel", type=float, default=0.0, help="Relative count tolerance (fraction)"
        )
        parser.add_argument(
            "--agg-tolerance-rel", type=float, default=1e-6, help="Relative aggregation_value tolerance"
        )
        parser.add_argument(
            "--regression-threshold-rel", type=float, default=0.10, help="Slowdown fraction = regression"
        )
        parser.add_argument(
            "--regression-threshold-ms", type=float, default=50.0, help="Min absolute Δms for a regression"
        )
        parser.add_argument(
            "--clickhouse-stats",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Read per-query resource stats from the query log (default on)",
        )
        parser.add_argument(
            "--query-log-table",
            type=str,
            default="system.query_log",
            help="Query-log table (default system.query_log; use query_log_archive on prod clusters)",
        )
        parser.add_argument(
            "--flush-query-log",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Run SYSTEM FLUSH LOGS before reading (default on; ignored if unprivileged)",
        )
        parser.add_argument("--query-log-wait", type=float, default=10.0, help="Seconds to poll for query-log rows")
        parser.add_argument("--report-path", type=str, default=None, help="Markdown report path")
        parser.add_argument("--json-path", type=str, default=None, help="Optional machine-readable JSON dump path")
        parser.add_argument("--base-url", type=str, default="https://us.posthog.com", help="Base URL for insight links")
        parser.add_argument("--max-source-json-chars", type=int, default=6000, help="Trim embedded query JSON")
        parser.add_argument("--fail-on-mismatch", action="store_true", help="Exit non-zero if any MISMATCH is found")

    def handle(self, *args: Any, **options: Any) -> None:
        insights = self._select_insights(options)
        if not insights:
            self.stdout.write(self.style.WARNING("No retention insights matched the given filters."))
            return

        self.stdout.write(f"Comparing {len(insights)} retention insight(s)…")
        run_id = uuid.uuid4().hex[:8]
        findings: list[InsightFinding] = []
        all_query_ids: list[str] = []

        for index, insight in enumerate(insights, start=1):
            finding = self._process_insight(insight, run_id, options)
            findings.append(finding)
            all_query_ids.extend(finding.legacy_query_ids)
            all_query_ids.extend(finding.dwh_query_ids)
            self._print_progress(index, len(insights), finding, options["verbosity"])

        if options["clickhouse_stats"] and not options["no_perf"] and all_query_ids:
            self._attach_resource_stats(findings, all_query_ids, options)

        aggregate = build_perf_aggregate(findings, worst_n=DEFAULT_WORST_N)
        run_meta = self._build_run_meta(findings, options)
        report = render_markdown_report(findings, aggregate, run_meta)

        report_path = options["report_path"] or f"retention_dwh_comparison_{run_id}.md"
        with open(report_path, "w") as handle:
            handle.write(report)
        if options["json_path"]:
            self._write_json(options["json_path"], findings, aggregate, run_meta)

        self._print_summary(run_meta["counts"], aggregate, report_path, options.get("json_path"))

        if options["fail_on_mismatch"] and run_meta["counts"]["mismatch"]:
            raise CommandError(f"{run_meta['counts']['mismatch']} insight(s) mismatched between variants")

    def _select_insights(self, options: dict[str, Any]) -> list[Insight]:
        queryset = Insight.objects.filter(saved=True, deleted=False, query__source__kind="RetentionQuery")
        if options["team_id"]:
            queryset = queryset.filter(team_id__in=options["team_id"])
        if options["insight_id"]:
            queryset = queryset.filter(id__in=options["insight_id"])
        if options["short_id"]:
            queryset = queryset.filter(short_id__in=options["short_id"])
        queryset = queryset.select_related("team")
        if options["sample"]:
            return list(queryset.order_by("?")[: options["sample"]])
        return list(queryset.order_by("created_at")[: options["limit"]])

    def _process_insight(self, insight: Insight, run_id: str, options: dict[str, Any]) -> InsightFinding:
        base_url = options["base_url"].rstrip("/")
        url = f"{base_url}/project/{insight.team_id}/insights/{insight.short_id}/edit"
        finding = InsightFinding(
            insight_id=insight.id,
            short_id=insight.short_id,
            team_id=insight.team_id,
            name=insight.name or "",
            url=url,
            status="OK",
        )
        try:
            source = insight.query.get("source") if isinstance(insight.query, dict) else None
            finding.has_breakdown = bool(isinstance(source, dict) and source.get("breakdownFilter"))
            if isinstance(source, dict):
                finding.source_json = _trim(json.dumps(source, indent=2, default=str), options["max_source_json_chars"])

            action, reason = classify_insight(insight)
            if action == "error":
                finding.status = "ERROR"
                finding.error_type = "ClassificationError"
                finding.error_detail = reason
                return finding
            if action == "skip":
                finding.status = "SKIPPED"
                finding.skip_reason = reason
                return finding

            self._run_comparison(insight, run_id, options, finding)
        except Exception as exc:
            finding.status = "ERROR"
            finding.error_type = type(exc).__name__
            finding.error_detail = traceback.format_exc()[-4000:]
        return finding

    def _run_comparison(self, insight: Insight, run_id: str, options: dict[str, Any], finding: InsightFinding) -> None:
        modifiers = create_default_modifiers_for_team(insight.team, HogQLQueryModifiers(timings=True))
        do_perf = not options["no_perf"]
        capture = do_perf and options["clickhouse_stats"]

        if options["warmup"]:
            run_variant(insight, False, modifiers)
            run_variant(insight, True, modifiers)

        legacy_run = run_variant(
            insight,
            False,
            modifiers,
            marker=f"rcmp_{run_id}_{insight.id}_legacy" if capture else None,
            capture_query_ids=capture,
        )
        dwh_run = run_variant(
            insight,
            True,
            modifiers,
            marker=f"rcmp_{run_id}_{insight.id}_dwh" if capture else None,
            capture_query_ids=capture,
        )
        finding.legacy_hogql = _trim(legacy_run.hogql, options["max_source_json_chars"])
        finding.dwh_hogql = _trim(dwh_run.hogql, options["max_source_json_chars"])
        finding.legacy_query_ids = legacy_run.query_ids
        finding.dwh_query_ids = dwh_run.query_ids

        finding.correctness = diff_retention_results(
            legacy_run.results,
            dwh_run.results,
            count_tol_abs=options["count_tolerance_abs"],
            count_tol_rel=options["count_tolerance_rel"],
            agg_tol_rel=options["agg_tolerance_rel"],
        )
        finding.status = finding.correctness.status

        if not do_perf:
            return

        wall_legacy = [legacy_run.wall_s * 1000]
        wall_dwh = [dwh_run.wall_s * 1000]
        ch_legacy = [legacy_run.ch_s * 1000]
        ch_dwh = [dwh_run.ch_s * 1000]
        for _ in range(max(0, options["perf_iterations"] - 1)):
            legacy_iter = run_variant(insight, False, modifiers)
            dwh_iter = run_variant(insight, True, modifiers)
            wall_legacy.append(legacy_iter.wall_s * 1000)
            wall_dwh.append(dwh_iter.wall_s * 1000)
            ch_legacy.append(legacy_iter.ch_s * 1000)
            ch_dwh.append(dwh_iter.ch_s * 1000)

        finding.perf = compute_perf_result(
            wall_legacy,
            wall_dwh,
            ch_legacy,
            ch_dwh,
            regression_rel=options["regression_threshold_rel"],
            regression_ms=options["regression_threshold_ms"],
        )

    def _attach_resource_stats(
        self, findings: list[InsightFinding], all_query_ids: list[str], options: dict[str, Any]
    ) -> None:
        self.stdout.write(f"Reading ClickHouse resource stats for {len(set(all_query_ids))} query id(s)…")
        stats_by_id = fetch_query_log_stats(
            all_query_ids,
            table=options["query_log_table"],
            flush=options["flush_query_log"],
            wait_seconds=options["query_log_wait"],
            log=lambda message: self.stdout.write(self.style.WARNING(f"  {message}")),
        )
        if not stats_by_id:
            return
        for finding in findings:
            finding.resource_legacy = aggregate_resource_stats(finding.legacy_query_ids, stats_by_id)
            finding.resource_dwh = aggregate_resource_stats(finding.dwh_query_ids, stats_by_id)
            if finding.resource_legacy and finding.resource_dwh and finding.resource_legacy.read_bytes > 0:
                finding.bytes_ratio = finding.resource_dwh.read_bytes / finding.resource_legacy.read_bytes

    def _build_run_meta(self, findings: list[InsightFinding], options: dict[str, Any]) -> dict[str, Any]:
        counts = {
            "compared": sum(1 for f in findings if f.status in ("OK", "MISMATCH")),
            "ok": sum(1 for f in findings if f.status == "OK"),
            "mismatch": sum(1 for f in findings if f.status == "MISMATCH"),
            "error": sum(1 for f in findings if f.status == "ERROR"),
            "skipped": sum(1 for f in findings if f.status == "SKIPPED"),
        }
        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "args": self._args_summary(options),
            "counts": counts,
            "regression_rel": options["regression_threshold_rel"],
            "regression_ms": options["regression_threshold_ms"],
            "max_cell_diffs": DEFAULT_MAX_CELL_DIFFS,
        }

    @staticmethod
    def _args_summary(options: dict[str, Any]) -> str:
        keys = [
            "team_id",
            "insight_id",
            "short_id",
            "limit",
            "sample",
            "perf_iterations",
            "warmup",
            "no_perf",
            "clickhouse_stats",
            "query_log_table",
        ]
        return ", ".join(f"{key}={options[key]}" for key in keys)

    def _write_json(
        self, path: str, findings: list[InsightFinding], aggregate: PerfAggregate, run_meta: dict[str, Any]
    ) -> None:
        payload = {
            "run_meta": run_meta,
            "aggregate": {
                "n_compared": aggregate.n_compared,
                "wall_ratio_dist": aggregate.wall_ratio_dist,
                "bytes_ratio_dist": aggregate.bytes_ratio_dist,
                "n_regressions": aggregate.n_regressions,
                "n_improvements": aggregate.n_improvements,
                "regression_insight_ids": [f.insight_id for f in aggregate.regressions],
                "improvement_insight_ids": [f.insight_id for f in aggregate.improvements],
            },
            "findings": [dataclasses.asdict(f) for f in findings],
        }
        with open(path, "w") as handle:
            json.dump(payload, handle, indent=2, default=str)

    def _print_progress(self, index: int, total: int, finding: InsightFinding, verbosity: int) -> None:
        if verbosity < 2 and finding.status in ("OK", "SKIPPED"):
            return
        style = {
            "OK": self.style.SUCCESS,
            "MISMATCH": self.style.ERROR,
            "ERROR": self.style.ERROR,
            "SKIPPED": self.style.WARNING,
        }.get(finding.status, self.style.NOTICE)
        detail = ""
        if finding.status == "MISMATCH" and finding.correctness:
            detail = f" cells={len(finding.correctness.cell_diffs)}"
        elif finding.status == "SKIPPED":
            detail = f" ({finding.skip_reason})"
        elif finding.status == "ERROR":
            detail = f" ({finding.error_type})"
        regressed = " REGRESSION" if finding.perf and finding.perf.is_regression else ""
        self.stdout.write(
            style(f"[{index}/{total}] {finding.status}{regressed} {finding.short_id} (team {finding.team_id}){detail}")
        )

    def _print_summary(
        self, counts: dict[str, int], aggregate: PerfAggregate, report_path: str, json_path: Optional[str]
    ) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(
            f"COMPARED={counts['compared']} OK={counts['ok']} MISMATCH={counts['mismatch']} "
            f"ERROR={counts['error']} SKIPPED={counts['skipped']} REGRESSIONS={aggregate.n_regressions}"
        )
        if aggregate.n_compared:
            wall_median = aggregate.wall_ratio_dist.get("median")
            bytes_median = aggregate.bytes_ratio_dist.get("median")
            self.stdout.write(
                f"Median wall ratio: {_fmt_ratio(wall_median)} | median bytes ratio: {_fmt_ratio(bytes_median)} | "
                f"improvements: {aggregate.n_improvements}"
            )
        self.stdout.write(self.style.SUCCESS(f"Report: {report_path}"))
        if json_path:
            self.stdout.write(self.style.SUCCESS(f"JSON: {json_path}"))
