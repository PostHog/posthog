"""Coverage report for the Grafana/VictoriaMetrics -> PostHog metrics migration.

We are moving internal observability off VictoriaMetrics/Grafana and onto our own
metrics product. Progress is the share of metric names referenced by the Grafana
dashboards (PostHog/grafana-dashboards repo) that also appear in the team's
`posthog.metric_series` table.

The Grafana inventory comes from a snapshot committed in the grafana-dashboards repo
(`coverage/coverage.json`), refreshed by `coverage/coverage_report.py` there. The
PostHog side can be computed live from ClickHouse for the internal project.

This module is import-safe without Django settings (pure functions only at module
level) so the report logic can be unit-tested without the app stack.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Prometheus client libraries expand histograms/summaries into per-series suffixes;
# PostHog ingests the OTLP metric under its base name, so a Grafana `_bucket`
# reference is covered when the base name was ingested.
ROLLUP_SUFFIXES = ("_bucket", "_count", "_sum", "_created")

# Cache live ingested-name lookups briefly; the page polls it and the scan is cheap
# but not free. The names flip slowly in practice.
INGESTED_NAMES_CACHE_KEY = "metrics_migration:ingested_names"
INGESTED_NAMES_CACHE_TTL = 300


def normalize_name(name: str) -> str:
    """Collapse a Prometheus rollup series name to its OTLP base name."""
    for suffix in ROLLUP_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def is_covered(grafana_name: str, ingested_names: set[str]) -> bool:
    return grafana_name in ingested_names or normalize_name(grafana_name) in ingested_names


def load_grafana_metrics(snapshot: dict) -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """Rebuild (metric -> dashboards, dashboard -> metrics) from the committed snapshot.

    The snapshot stores dashboards with covered/uncovered counts rather than name
    lists, so dashboard-level name sets can only be reconstructed for uncovered
    metrics. That is enough for the page: it renders counts and the uncovered list.
    """
    grafana_metrics: dict[str, list[str]] = {}
    dashboard_metrics: dict[str, set[str]] = {}
    for metric in snapshot.get("uncovered", []):
        name = metric["name"]
        refs = list(metric.get("dashboards", []))
        grafana_metrics[name] = refs
        for title in refs:
            dashboard_metrics.setdefault(title, set()).add(name)
    return grafana_metrics, dashboard_metrics


def report_from_snapshot(snapshot: dict) -> dict:
    """Return the snapshot as the page consumes it (it is already the report shape)."""
    return snapshot


def build_report(
    *,
    grafana_metrics: dict[str, list[str]],
    dashboard_metrics: dict[str, set[str]],
    ingested: set[str],
) -> dict:
    """Join the Grafana metric inventory against ingested PostHog metric names."""
    covered_names = {name for name in grafana_metrics if is_covered(name, ingested)}
    uncovered_names = set(grafana_metrics) - covered_names

    dashboards = []
    for title, metrics in dashboard_metrics.items():
        covered = {name for name in metrics if is_covered(name, ingested)}
        dashboards.append(
            {
                "title": title,
                "metric_count": len(metrics),
                "covered_metrics": len(covered),
                "uncovered_metrics": len(metrics) - len(covered),
                "coverage_pct": round(100 * len(covered) / len(metrics), 1) if metrics else 0.0,
                "status": "covered" if len(covered) == len(metrics) else ("partial" if covered else "missing"),
            }
        )
    dashboards.sort(key=lambda d: (-d["coverage_pct"], d["title"]))

    total = len(grafana_metrics)
    return {
        "summary": {
            "grafana_metric_names": total,
            "posthog_ingested_names": len(ingested),
            "covered": len(covered_names),
            "uncovered": len(uncovered_names),
            "coverage_pct": round(100 * len(covered_names) / total, 1) if total else 0.0,
            "dashboards_total": len(dashboards),
            "dashboards_fully_covered": sum(1 for d in dashboards if d["status"] == "covered"),
        },
        "dashboards": dashboards,
        "uncovered": [{"name": name, "dashboards": sorted(grafana_metrics[name])} for name in sorted(uncovered_names)],
    }


def load_snapshot() -> Optional[dict]:
    """Load the committed Grafana coverage snapshot, if present on this deploy."""
    import json
    import os

    path = os.environ.get(
        "GRAFANA_COVERAGE_SNAPSHOT",
        os.path.join(os.path.dirname(__file__), "data", "grafana_metrics_coverage.json"),
    )
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("metrics_migration: failed to load snapshot at %s", path)
        return None


def ingested_metric_names(team) -> set[str]:
    """Distinct metric names recently ingested for a team, read from `metric_series`.

    Reads the series table rather than the raw datapoints: same names, far fewer rows.
    """
    from django.core.cache import cache

    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import Workload

    cached = cache.get(INGESTED_NAMES_CACHE_KEY)
    if cached is not None:
        return set(cached)

    rows = sync_execute(
        """
        SELECT DISTINCT metric_name
        FROM metric_series
        WHERE team_id = %(team_id)s
          AND last_seen >= now() - INTERVAL 7 DAY
        """,
        {"team_id": team.id},
        # metric_series lives on the dedicated LOGS cluster, not the analytics one.
        workload=Workload.LOGS,
    )
    names = sorted({row[0] for row in rows})
    cache.set(INGESTED_NAMES_CACHE_KEY, names, INGESTED_NAMES_CACHE_TTL)
    return set(names)


def merge_live_ingested(report: dict, ingested: set[str]) -> dict:
    """Recompute coverage against live ingested names, keeping the Grafana inventory.

    The snapshot only names uncovered metrics, so a metric that started flowing since
    the snapshot was generated moves from uncovered to covered here; per-metric detail
    for already-covered metrics stays as snapshotted.
    """
    grafana_metrics, dashboard_metrics = load_grafana_metrics(report)
    summary = dict(report.get("summary", {}))

    newly_covered = [name for name in grafana_metrics if is_covered(name, ingested)]
    covered = summary.get("covered", 0) + len(newly_covered)
    total = summary.get("grafana_metric_names", 0)
    summary["covered"] = covered
    summary["uncovered"] = max(total - covered, 0)
    summary["coverage_pct"] = round(100 * covered / total, 1) if total else 0.0
    summary["posthog_ingested_names"] = len(ingested)

    still_uncovered = [m for m in report.get("uncovered", []) if not is_covered(m["name"], ingested)]
    return {**report, "summary": summary, "uncovered": still_uncovered, "live": True}
