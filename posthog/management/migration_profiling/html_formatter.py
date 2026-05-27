"""Rich self-contained HTML report for the migration profile.

Renders one HTML file with:
- An executive-summary tile grid up top
- A sticky table-of-contents nav
- Sortable, scannable tables (click any header to sort)
- Per-migration duration bars (Apply total split into SQL vs Python overhead)
- A link to the interactive pyinstrument flame view
- All CSS + JS inline — no external requests, no CDN dependency

Companion to ``formatters.py`` (which writes plain Markdown). Both consume the
same ``ProfileRun`` dataclass + pyinstrument aggregates.
"""

from __future__ import annotations

import html as _html
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from posthog.management.migration_profiling.dead_code.models import Finding
from posthog.management.migration_profiling.dead_code.waste_analysis import (
    AVOIDABLE_CATEGORIES,
    WasteBreakdown,
    WasteCategory,
)
from posthog.management.migration_profiling.formatters import (
    P95,
    ProfileRun,
    _build_children_index,
    _classify_runpython,
    _effective_ops,
    _fmt_ms,
    _percentile,
    _top_opportunities_section,
)
from posthog.management.migration_profiling.pyinstrument_parse import PyinstrumentAggregate

TOP_OPS = 50
TOP_MIGRATIONS = 30
TOP_SQL = 30
TOP_PY_FUNCS = 30
LOW_SQL_THRESHOLD_MS = 10.0


def _esc(s: Any) -> str:
    return _html.escape(str(s)) if s is not None else ""


def _bar_cell(value_ms: float, max_ms: float, label: str | None = None) -> str:
    """A cell showing a horizontal bar + numeric label."""
    pct = (value_ms / max_ms * 100.0) if max_ms > 0 else 0.0
    label_txt = label if label is not None else _fmt_ms(value_ms)
    return (
        f'<td data-sort="{value_ms:.3f}" class="num">'
        f'<div class="bar-cell"><div class="bar" style="width:{pct:.1f}%"></div>'
        f'<span class="bar-label">{_esc(label_txt)}</span></div></td>'
    )


def _split_bar_cell(sql_ms: float, python_ms: float, max_ms: float, label: str) -> str:
    total = sql_ms + python_ms
    if max_ms <= 0:
        max_ms = total or 1.0
    sql_pct = sql_ms / max_ms * 100.0
    py_pct = python_ms / max_ms * 100.0
    return (
        f'<td data-sort="{total:.3f}" class="num">'
        f'<div class="bar-cell">'
        f'<div class="bar bar-sql" style="width:{sql_pct:.1f}%" title="SQL {_fmt_ms(sql_ms)}"></div>'
        f'<div class="bar bar-py" style="width:{py_pct:.1f}%" title="Python {_fmt_ms(python_ms)}"></div>'
        f'<span class="bar-label">{_esc(label)}</span></div></td>'
    )


def _stat_tile(label: str, value: str, sub: str | None = None) -> str:
    sub_html = f'<div class="tile-sub">{_esc(sub)}</div>' if sub else ""
    return (
        f'<div class="tile">'
        f'<div class="tile-value">{_esc(value)}</div>'
        f'<div class="tile-label">{_esc(label)}</div>'
        f"{sub_html}</div>"
    )


_STYLE = """
:root {
  --bg: #fafafa;
  --surface: #ffffff;
  --border: #e6e6ea;
  --text: #1f2328;
  --muted: #6e7681;
  --accent: #2563eb;
  --accent-soft: #dbeafe;
  --sql: #2563eb;
  --py: #f97316;
  --warn: #d97706;
  --code-bg: #f3f4f6;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
body { padding: 0 32px 80px; max-width: 1400px; margin: 0 auto; }
h1 { font-size: 28px; margin: 32px 0 8px; }
h2 { font-size: 20px; margin: 40px 0 12px; padding-top: 8px; border-top: 1px solid var(--border); }
h3 { font-size: 16px; margin: 24px 0 8px; color: var(--muted); }
p { margin: 8px 0; }
code { background: var(--code-bg); padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }
.muted { color: var(--muted); }

nav.toc {
  position: sticky; top: 0; z-index: 10;
  background: rgba(250,250,250,0.95); backdrop-filter: blur(8px);
  padding: 12px 0; margin: -8px -32px 24px; padding-left: 32px; padding-right: 32px;
  border-bottom: 1px solid var(--border);
  font-size: 13px; display: flex; gap: 14px; flex-wrap: wrap; align-items: center;
}
nav.toc a { color: var(--muted); text-decoration: none; padding: 3px 8px; border-radius: 4px; }
nav.toc a:hover { background: var(--accent-soft); color: var(--accent); }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin: 16px 0 32px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px 16px; }
.tile-value { font-size: 24px; font-weight: 600; letter-spacing: -0.5px; }
.tile-label { font-size: 12px; color: var(--muted); margin-top: 2px;
  text-transform: uppercase; letter-spacing: 0.5px; }
.tile-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.tile.warn .tile-value { color: var(--warn); }
.tile.accent .tile-value { color: var(--accent); }

.headline { background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--accent);
  padding: 16px 18px; border-radius: 6px; margin: 0 0 24px; }

table { width: 100%; border-collapse: collapse; background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin: 8px 0; }
th, td { padding: 8px 10px; text-align: left; vertical-align: middle;
  border-bottom: 1px solid var(--border); font-size: 13px; }
th { background: #f5f5f7; font-weight: 600; cursor: pointer; user-select: none;
  position: relative; white-space: nowrap; }
th:hover { background: var(--accent-soft); color: var(--accent); }
th.asc::after { content: " ↑"; opacity: 0.6; }
th.desc::after { content: " ↓"; opacity: 0.6; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafbfc; }
td.num { font-variant-numeric: tabular-nums; }

.bar-cell { position: relative; display: flex; align-items: center; min-width: 140px; }
.bar { height: 18px; background: var(--accent); border-radius: 3px;
  opacity: 0.18; flex-shrink: 0; }
.bar.bar-sql { background: var(--sql); opacity: 0.45; }
.bar.bar-py { background: var(--py); opacity: 0.45; }
.bar-label { margin-left: 8px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.bar-row .bar:not(:first-child) { margin-left: 0; }

.legend { display: inline-flex; gap: 12px; font-size: 12px; color: var(--muted); margin: 8px 0; }
.legend .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 4px; vertical-align: middle; }
.legend .sw-sql { background: var(--sql); opacity: 0.6; }
.legend .sw-py { background: var(--py); opacity: 0.6; }

details { background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
  padding: 6px 10px; margin: 4px 0; }
details summary { cursor: pointer; color: var(--accent); font-size: 12px; }
details pre { margin: 8px 0 0; white-space: pre-wrap; word-break: break-word;
  background: var(--code-bg); padding: 8px; border-radius: 3px; font-size: 12px; }

.section-lead { color: var(--muted); margin: 4px 0 14px; max-width: 800px; }
.section-lead strong { color: var(--text); }

.pill { display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.pill.ease-easy { background: #dcfce7; color: #166534; }
.pill.ease-medium { background: #fef3c7; color: #92400e; }
.pill.ease-hard { background: #fee2e2; color: #991b1b; }

.waste-headline { font-size: 15px; background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--warn); padding: 14px 18px; border-radius: 6px; margin: 0 0 18px; }
.waste-bar { display: flex; height: 36px; border-radius: 6px; overflow: hidden;
  border: 1px solid var(--border); margin: 0 0 12px; box-shadow: inset 0 1px 2px rgba(0,0,0,0.05); }
.waste-seg { height: 100%; transition: opacity 0.15s; }
.waste-seg:hover { opacity: 0.7; }
.waste-legend { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 8px; margin: 0 0 24px; font-size: 13px; }
.waste-legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 8px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 4px; }
.waste-sw { display: inline-block; width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }
.waste-legend-label { flex: 1; }
.waste-legend-time { color: var(--muted); font-variant-numeric: tabular-nums; }
.waste-legend-verdict { font-size: 10px; padding: 2px 6px; border-radius: 8px;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.verdict-avoid { background: #fee2e2; color: #991b1b; }
.verdict-essential { background: #dcfce7; color: #166534; }
"""


_SCRIPT = """
(function() {
  function sortKey(cell) {
    const ds = cell.dataset.sort;
    if (ds !== undefined) return ds;
    return cell.textContent.trim();
  }
  function applySort(table, colIdx, asc) {
    const tbody = table.tBodies[0];
    if (!tbody) return;
    const rows = Array.from(tbody.rows);
    rows.sort((a, b) => {
      const va = sortKey(a.cells[colIdx]);
      const vb = sortKey(b.cells[colIdx]);
      const na = parseFloat(va), nb = parseFloat(vb);
      if (!isNaN(na) && !isNaN(nb)) return asc ? na - nb : nb - na;
      return asc ? va.localeCompare(vb) : vb.localeCompare(va);
    });
    rows.forEach(r => tbody.appendChild(r));
  }
  document.querySelectorAll('table.sortable').forEach(table => {
    const ths = table.tHead ? table.tHead.querySelectorAll('th') : [];
    ths.forEach((th, idx) => {
      th.addEventListener('click', () => {
        const asc = !th.classList.contains('asc');
        ths.forEach(x => { x.classList.remove('asc'); x.classList.remove('desc'); });
        th.classList.add(asc ? 'asc' : 'desc');
        applySort(table, idx, asc);
      });
    });
  });
})();
"""


def render_html_report(
    runs: list[ProfileRun],
    pyinstrument_paths: dict[str, Path] | None = None,
    pyinstrument_aggregates: dict[str, PyinstrumentAggregate] | None = None,
    findings: list[Finding] | None = None,
    waste: WasteBreakdown | None = None,
) -> str:
    pyinstrument_paths = pyinstrument_paths or {}
    pyinstrument_aggregates = pyinstrument_aggregates or {}
    findings = findings or []

    all_ops = [op for run in runs for op in _effective_ops(run.ops)]
    sql_total_ms = sum(op["duration_ms"] for op in all_ops)
    apply_total_ms = sum(s for run in runs for s in run.migration_summaries.values())
    python_overhead_ms = max(apply_total_ms - sql_total_ms, 0.0) if apply_total_ms else 0.0
    overhead_share = (python_overhead_ms / apply_total_ms * 100.0) if apply_total_ms else 0.0
    pyinstrument_total_s = sum(a.total_duration_s for a in pyinstrument_aggregates.values())
    total_migrations = sum(len(run.migration_summaries) for run in runs) or len(
        {(op["app_label"], op["migration_name"]) for op in all_ops}
    )
    sdas_noop_count = sum(
        1 for op in all_ops if op["operation_type"] == "SeparateDatabaseAndState" and op["duration_ms"] < 1.0
    )

    body: list[str] = []

    body.append('<nav class="toc">')
    for section_id, label in [
        ("waste", "Where time goes"),
        ("summary", "Summary"),
        ("opportunities", "Opportunities"),
        ("dead-code", "Dead code"),
        ("aggregates", "Aggregates"),
        ("slowest-migrations", "Slowest migrations"),
        ("slowest-ops", "Slowest operations"),
        ("slowest-sql", "Slowest SQL"),
        ("useless-runpython", "RunPython no-ops"),
        ("squash-impact", "Squash impact"),
        ("squash-clusters", "Squash clusters"),
        ("python", "Python"),
    ]:
        body.append(f'<a href="#{section_id}">{_esc(label)}</a>')
    body.append("</nav>")

    body.append("<h1>Migration profile report</h1>")

    if waste and waste.apply_total_ms:
        body.append('<h2 id="waste">Where does the time go?</h2>')
        body.append(_html_waste_distribution(waste))
    # Metadata line.
    meta_bits = []
    for run in runs:
        m = run.meta
        meta_bits.append(
            f"{_esc(run.database)} · Django {_esc(m.get('django_version', '?'))} · "
            f"git {_esc((m.get('git_sha') or '?')[:12])} · {_esc(m.get('started_at', ''))}"
        )
    body.append(f'<p class="muted">{" · ".join(meta_bits)}</p>')

    # ---- summary ----
    body.append('<h2 id="summary">Executive summary</h2>')
    body.append('<div class="tiles">')
    body.append(_stat_tile("Migrations", str(total_migrations)))
    body.append(_stat_tile("Operations", str(len(all_ops))))
    if apply_total_ms:
        body.append(_stat_tile("Migration.apply wall-clock", _fmt_ms(apply_total_ms)))
    if pyinstrument_total_s:
        body.append(_stat_tile("Python runtime (pyinstrument)", f"{pyinstrument_total_s:.1f}s"))
    body.append(_stat_tile("SQL / DB time", _fmt_ms(sql_total_ms), "sum of database_forwards"))
    if python_overhead_ms:
        body.append(
            _stat_tile(
                "Python overhead",
                _fmt_ms(python_overhead_ms),
                f"{overhead_share:.0f}% of apply time",
            ).replace('class="tile"', 'class="tile warn"')
        )
    if sdas_noop_count:
        body.append(
            _stat_tile(
                "SDAS no-op ops",
                str(sdas_noop_count),
                "0 DB work, full Python tax",
            )
        )
    body.append("</div>")

    body.append('<div class="headline">')
    body.append(
        "<strong>The headline cost is Django's project-state machine, not SQL.</strong> "
        "Every migration triggers <code>state.clone()</code> + <code>state.render()</code> "
        "against every loaded model. Squashing reduces this Python tax. The "
        "<em>Slowest migrations</em> table below shows the SQL/Python split per migration "
        "with stacked bars."
    )
    body.append("</div>")

    body.append('<h2 id="opportunities">Top opportunities</h2>')
    body.append(_html_top_opportunities(runs, all_ops, findings, waste))

    if findings:
        body.append('<h2 id="dead-code">Dead-code findings (AST detectors)</h2>')
        body.append(_html_findings(findings))

    # ---- aggregates ----
    body.append('<h2 id="aggregates">Aggregates</h2>')
    body.append("<h3>By database</h3>")
    body.append(_html_table_by_database(runs))
    body.append("<h3>By app</h3>")
    body.append(_html_table_by_app(all_ops))
    body.append("<h3>By operation type</h3>")
    body.append(_html_table_by_optype(all_ops))

    # ---- slowest migrations ----
    body.append('<h2 id="slowest-migrations">Top 30 slowest migrations</h2>')
    body.append(
        '<div class="legend">'
        '<span><span class="sw sw-sql"></span> SQL</span>'
        '<span><span class="sw sw-py"></span> Python overhead</span>'
        "</div>"
    )
    body.append(_html_table_slowest_migrations(runs, waste))

    # ---- slowest ops ----
    body.append('<h2 id="slowest-ops">Top 50 slowest operations</h2>')
    body.append(_html_table_slowest_ops(all_ops))

    # ---- slowest SQL ----
    body.append('<h2 id="slowest-sql">Top 30 slowest SQL statements</h2>')
    body.append(_html_table_slowest_sql(all_ops))

    # ---- useless RunPython ----
    body.append('<h2 id="useless-runpython">RunPython no-ops on a fresh DB</h2>')
    body.append(_html_useless_runpython(runs))

    # ---- squash impact ----
    body.append('<h2 id="squash-impact">Squash impact estimate</h2>')
    body.append(_html_squash_impact(runs))

    # ---- squash clusters ----
    body.append('<h2 id="squash-clusters">Squash clusters (consecutive low-cost)</h2>')
    body.append(_html_squash_clusters(runs))

    # ---- python ----
    if pyinstrument_aggregates or pyinstrument_paths:
        body.append('<h2 id="python">Python state machine (pyinstrument)</h2>')
        for db, agg in pyinstrument_aggregates.items():
            body.append(f"<h3>{_esc(db)}</h3>")
            body.append(
                f'<p class="muted">Total duration: {agg.total_duration_s:.1f}s'
                + (f" ({agg.sample_count} samples)" if agg.sample_count else "")
                + "</p>"
            )
            if db in pyinstrument_paths:
                body.append(
                    f"<p>Interactive flame view: "
                    f'<a href="{_esc(pyinstrument_paths[db].name)}">'
                    f"{_esc(pyinstrument_paths[db].name)}</a></p>"
                )
            body.append("<h3>Top by self time</h3>")
            body.append(_html_table_py(agg.by_self, "Self s"))
            body.append("<h3>Top by cumulative time</h3>")
            body.append(_html_table_py(agg.by_cumulative, "Cumulative s"))

    return _HEAD + _STYLE + _MID + "".join(body) + "<script>" + _SCRIPT + "</script>" + _TAIL


_HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Migration profile report</title>
<style>
"""
_MID = """</style>
</head><body>
"""
_TAIL = "</body></html>"


# ---------- table builders ----------


def _html_table_by_database(runs: list[ProfileRun]) -> str:
    rows_html = []
    for run in runs:
        effective = _effective_ops(run.ops)
        total_ms = sum(op["duration_ms"] for op in effective)
        durations = [op["duration_ms"] for op in effective if op["duration_ms"] > 0]
        p95 = _percentile(durations, P95)
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(run.database)}</td>"
            f"<td class='num' data-sort='{len(run.migration_summaries)}'>{len(run.migration_summaries) or '—'}</td>"
            f"<td class='num' data-sort='{len(effective)}'>{len(effective)}</td>"
            f"<td class='num' data-sort='{total_ms:.3f}'>{_fmt_ms(total_ms)}</td>"
            f"<td class='num' data-sort='{p95:.3f}'>{_fmt_ms(p95)}</td>"
            f"</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        "<th>Database</th><th>Migrations</th><th>Ops</th><th>Total SQL</th><th>p95 op</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_table_by_app(ops: list[dict[str, Any]]) -> str:
    by_app: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for op in ops:
        by_app[op["app_label"]].append(op)
    items = sorted(by_app.items(), key=lambda x: -sum(o["duration_ms"] for o in x[1]))
    max_total = max((sum(o["duration_ms"] for o in app_ops) for _, app_ops in items), default=1.0) or 1.0
    rows_html = []
    for app, app_ops in items:
        total_ms = sum(op["duration_ms"] for op in app_ops)
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(app)}</td>"
            f"<td class='num'>{len({(o['app_label'], o['migration_name']) for o in app_ops})}</td>"
            f"<td class='num'>{len(app_ops)}</td>"
            f"{_bar_cell(total_ms, max_total)}"
            f"</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        "<th>App</th><th>Migrations</th><th>Ops</th><th>Total SQL</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_table_by_optype(ops: list[dict[str, Any]]) -> str:
    by_type: dict[str, list[float]] = defaultdict(list)
    for op in ops:
        by_type[op["operation_type"]].append(op["duration_ms"])
    items = sorted(by_type.items(), key=lambda x: -sum(x[1]))
    rows_html = []
    for op_type, durations in items:
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(op_type)}</td>"
            f"<td class='num'>{len(durations)}</td>"
            f"<td class='num' data-sort='{sum(durations):.3f}'>{_fmt_ms(sum(durations))}</td>"
            f"<td class='num' data-sort='{(statistics.median(durations) if durations else 0.0):.3f}'>{_fmt_ms(statistics.median(durations) if durations else 0.0)}</td>"
            f"<td class='num' data-sort='{_percentile(durations, P95):.3f}'>{_fmt_ms(_percentile(durations, P95))}</td>"
            f"<td class='num' data-sort='{(max(durations) if durations else 0):.3f}'>{_fmt_ms(max(durations) if durations else 0.0)}</td>"
            f"</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        "<th>Op type</th><th>Count</th><th>Total</th><th>p50</th><th>p95</th><th>Max</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_table_slowest_migrations(runs: list[ProfileRun], waste: WasteBreakdown | None = None) -> str:
    sql_by_mig: dict[tuple[str, str, str], float] = defaultdict(float)
    ops_count_by_mig: dict[tuple[str, str, str], int] = defaultdict(int)
    heaviest_by_mig: dict[tuple[str, str, str], dict[str, Any]] = {}
    ops_by_mig: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        for op in _effective_ops(run.ops):
            key = (run.database, op["app_label"], op["migration_name"])
            sql_by_mig[key] += op["duration_ms"]
            ops_count_by_mig[key] += 1
            ops_by_mig[key].append(op)
            existing = heaviest_by_mig.get(key)
            if existing is None or op["duration_ms"] > existing["duration_ms"]:
                heaviest_by_mig[key] = op

    def _verdict(key: tuple[str, str, str]) -> tuple[str, str]:
        """Returns (label, pill_class)."""
        if waste is None:
            return ("", "")
        from posthog.management.migration_profiling.formatters import _verdict_for_ops

        label = _verdict_for_ops(ops_by_mig.get(key, []))
        if label == "fully avoidable":
            return (label, "ease-easy")
        if label == "essential":
            return (label, "ease-hard")
        if label.startswith("mixed"):
            return (label, "ease-medium")
        return (label, "")

    aggregates = []
    for run in runs:
        for (app, name), apply_ms in run.migration_summaries.items():
            key = (run.database, app, name)
            sql_ms = sql_by_mig.get(key, 0.0)
            python_ms = max(apply_ms - sql_ms, 0.0)
            aggregates.append(
                (key, apply_ms, sql_ms, python_ms, ops_count_by_mig.get(key, 0), heaviest_by_mig.get(key))
            )
    aggregates.sort(key=lambda x: -x[1])
    max_apply = max((a[1] for a in aggregates), default=1.0) or 1.0

    rows_html = []
    for i, (key, apply_ms, sql_ms, python_ms, n_ops, heaviest) in enumerate(aggregates[:TOP_MIGRATIONS], start=1):
        heaviest_lbl = f"{_esc(heaviest['operation_type'])} ({_fmt_ms(heaviest['duration_ms'])})" if heaviest else "—"
        verdict_label, verdict_class = _verdict(key)
        verdict_html = f"<span class='pill {verdict_class}'>{_esc(verdict_label)}</span>" if verdict_label else ""
        rows_html.append(
            f"<tr>"
            f"<td class='num'>{i}</td>"
            f"<td>{_esc(key[0])}</td>"
            f"<td>{_esc(key[1])}</td>"
            f"<td><code>{_esc(key[2])}</code></td>"
            f"{_split_bar_cell(sql_ms, python_ms, max_apply, _fmt_ms(apply_ms))}"
            f"<td class='num' data-sort='{sql_ms:.3f}'>{_fmt_ms(sql_ms)}</td>"
            f"<td class='num' data-sort='{python_ms:.3f}'>{_fmt_ms(python_ms)}</td>"
            f"<td class='num'>{n_ops}</td>"
            f"<td>{verdict_html}</td>"
            f"<td>{heaviest_lbl}</td>"
            f"</tr>"
        )
    headers = (
        "<th>#</th><th>DB</th><th>App</th><th>Migration</th><th>Apply (SQL+Py)</th>"
        "<th>SQL</th><th>Python</th><th>Ops</th><th>Verdict</th><th>Heaviest op</th>"
    )
    return (
        '<table class="sortable"><thead><tr>'
        + headers
        + "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )


def _html_table_slowest_ops(ops: list[dict[str, Any]]) -> str:
    sorted_ops = sorted(ops, key=lambda o: -o["duration_ms"])[:TOP_OPS]
    max_d = sorted_ops[0]["duration_ms"] if sorted_ops else 1.0
    rows_html = []
    for i, op in enumerate(sorted_ops, start=1):
        rows_html.append(
            f"<tr>"
            f"<td class='num'>{i}</td>"
            f"<td>{_esc(op['database'])}</td>"
            f"<td>{_esc(op['app_label'])}</td>"
            f"<td><code>{_esc(op['migration_name'])}</code></td>"
            f"<td>{_esc(op['operation_type'])}</td>"
            f"<td>{_esc(op['describe'][:80])}</td>"
            f"{_bar_cell(op['duration_ms'], max_d)}"
            f"<td class='num'>{op['sql_count']}</td>"
            f"</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        "<th>#</th><th>DB</th><th>App</th><th>Migration</th><th>Op</th><th>Describe</th><th>Duration</th><th>SQL</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_table_slowest_sql(ops: list[dict[str, Any]]) -> str:
    flat: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for op in ops:
        for stmt in op.get("sql_statements", []):
            flat.append((op, stmt))
    flat.sort(key=lambda x: -x[1]["duration_ms"])
    max_d = flat[0][1]["duration_ms"] if flat else 1.0
    rows_html = []
    for i, (op, stmt) in enumerate(flat[:TOP_SQL], start=1):
        full_sql = stmt["sql"]
        preview = full_sql[:140].replace("\n", " ")
        rows_html.append(
            f"<tr>"
            f"<td class='num'>{i}</td>"
            f"<td><code>{_esc(op['app_label'])}.{_esc(op['migration_name'])}</code></td>"
            f"<td>{_esc(op['operation_type'])}</td>"
            f"<td>{_esc(stmt['source'])}</td>"
            f"{_bar_cell(stmt['duration_ms'], max_d)}"
            f"<td><details><summary>{_esc(preview)}</summary><pre>{_esc(full_sql)}</pre></details></td>"
            f"</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        "<th>#</th><th>Migration</th><th>Op</th><th>Source</th><th>Duration</th><th>SQL</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_top_opportunities(
    runs: list[ProfileRun],
    all_ops: list[dict[str, Any]],
    findings: list[Finding] | None = None,
    waste: WasteBreakdown | None = None,
) -> str:
    """Pull the synthesized opportunity items from the markdown helper but
    render as a richer HTML table with effort-pill styling."""
    md = _top_opportunities_section(runs, all_ops, findings or [], waste)
    # If "no opportunities" — bail.
    if "no opportunities" in md:
        return '<p class="muted"><em>no opportunities identified</em></p>'

    # The markdown table is `| Opportunity | Est. savings | Effort | Detail |`.
    lines = md.splitlines()
    rows = []
    inside_table = False
    for line in lines:
        if line.startswith("| Opportunity"):
            inside_table = True
            continue
        if inside_table and line.startswith("| ---"):
            continue
        if inside_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 4:
                rows.append(cells)
        elif inside_table:
            break

    ease_class = {"easy": "ease-easy", "medium": "ease-medium", "hard": "ease-hard"}
    rows_html = []
    for title, savings, effort, detail in rows:
        rows_html.append(
            f"<tr>"
            f"<td><strong>{_esc(title)}</strong></td>"
            f"<td class='num'>{_esc(savings)}</td>"
            f"<td><span class='pill {ease_class.get(effort, '')}'>{_esc(effort)}</span></td>"
            f"<td>{_esc(detail)}</td>"
            f"</tr>"
        )
    lead = (
        '<p class="section-lead"><em>Auto-synthesized punch list, ranked by '
        "impact × ease. Walk down the rows top-to-bottom — each one links to "
        "the section with the full per-migration breakdown.</em></p>"
    )
    return (
        lead + '<table class="sortable"><thead><tr>'
        "<th>Opportunity</th><th>Est. savings</th><th>Effort</th><th>Detail</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


_WASTE_CATEGORY_LABELS = {
    WasteCategory.ESSENTIAL_CREATE: "Essential creates",
    WasteCategory.ESSENTIAL_RESHAPE: "Essential reshapes",
    WasteCategory.REDUNDANT_RESHAPE: "Redundant reshapes",
    WasteCategory.DEAD_TARGET: "Ops on dead targets",
    WasteCategory.REMOVAL: "Removals",
    WasteCategory.BACKFILL: "RunPython backfills (no rows)",
    WasteCategory.STATE_ONLY: "State-only ops (SDAS etc.)",
    WasteCategory.BOOTSTRAP: "Bootstrap DDL",
    WasteCategory.UNKNOWN: "Unclassified",
}

# Color per category for the stacked bar.
_WASTE_CATEGORY_COLORS = {
    WasteCategory.ESSENTIAL_CREATE: "#16a34a",  # green
    WasteCategory.ESSENTIAL_RESHAPE: "#22c55e",  # green-ish
    WasteCategory.REDUNDANT_RESHAPE: "#f59e0b",  # amber
    WasteCategory.DEAD_TARGET: "#ef4444",  # red
    WasteCategory.REMOVAL: "#dc2626",  # darker red
    WasteCategory.BACKFILL: "#f97316",  # orange
    WasteCategory.STATE_ONLY: "#fbbf24",  # yellow
    WasteCategory.BOOTSTRAP: "#64748b",  # slate
    WasteCategory.UNKNOWN: "#94a3b8",  # gray
    "state_essential": "#3b82f6",  # blue (Django state, essential mig)
    "state_avoidable": "#a855f7",  # purple (Django state, avoidable mig)
}


def _html_waste_distribution(waste: WasteBreakdown) -> str:
    """Render the headline 'where time goes' as two stacked bars:

    1. **Top-level slab bar**: essential SQL / avoidable SQL / state-machine.
    2. **Per-category bar**: same segments as the markdown breakdown, with
       individual hover tooltips.
    """
    apply_total = waste.apply_total_ms
    if apply_total <= 0:
        return ""
    essential_sql = waste.essential_sql_ms
    avoidable_sql = waste.avoidable_sql_ms
    sm_total = waste.state_machine_total_ms
    sm_floor = min(sm_total, waste.one_migration_apply_floor_ms)
    sm_amortizable = waste.amortizable_state_machine_ms
    avoidable = waste.total_avoidable_ms
    floor = waste.theoretical_floor_ms
    avoid_pct = waste.avoidable_share * 100.0

    headline = (
        f"<p class='waste-headline'><strong>~{_fmt_ms(avoidable)} of {_fmt_ms(apply_total)} "
        f"({avoid_pct:.0f}%) is reclaimable</strong> if you re-squash to the final schema. "
        f"Theoretical floor: <strong>{_fmt_ms(floor)}</strong> — what it would cost to build "
        "the current schema as one mega-squashed initial migration. Everything above that "
        "line is migration history overhead.</p>"
    )

    # ---- Top-level slab bar.
    top_slabs = [
        ("essential_sql", essential_sql, "Essential SQL (final schema)", "#16a34a"),
        ("avoidable_sql", avoidable_sql, "Avoidable SQL (dead, backfills)", "#dc2626"),
        ("sm_floor", sm_floor, "Django state-machine floor (one Migration.apply)", "#3b82f6"),
        ("sm_amortizable", sm_amortizable, "Django state-machine (amortizable via squash)", "#a855f7"),
    ]
    top_bar_parts = []
    for _key, ms, label, color in top_slabs:
        if ms <= 0:
            continue
        pct = ms / apply_total * 100.0
        top_bar_parts.append(
            f'<div class="waste-seg" style="width:{pct:.2f}%;background:{color}" '
            f'title="{_esc(label)}: {_fmt_ms(ms)} ({pct:.1f}%)"></div>'
        )
    top_legend_parts = []
    for key, ms, label, color in top_slabs:
        if ms <= 0:
            continue
        pct = ms / apply_total * 100.0
        is_avoid = key in {"avoidable_sql", "sm_amortizable"}
        top_legend_parts.append(
            f'<div class="waste-legend-item">'
            f'<span class="waste-sw" style="background:{color}"></span>'
            f'<span class="waste-legend-label">{_esc(label)}</span>'
            f'<span class="waste-legend-time">{_fmt_ms(ms)} ({pct:.1f}%)</span>'
            f'<span class="waste-legend-verdict {"verdict-avoid" if is_avoid else "verdict-essential"}">'
            f"{'reclaimable' if is_avoid else 'floor'}</span>"
            "</div>"
        )

    # ---- Per-category bar.
    detail_segments: list[tuple[str, float, str, str]] = []
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
        if ms <= 0:
            continue
        detail_segments.append((cat, ms, _WASTE_CATEGORY_LABELS[cat], _WASTE_CATEGORY_COLORS[cat]))
    if waste.state_machine_essential_ms > 0:
        detail_segments.append(
            (
                "state_essential",
                waste.state_machine_essential_ms,
                "Django state (essential mig)",
                _WASTE_CATEGORY_COLORS["state_essential"],
            )
        )
    if waste.state_machine_avoidable_ms > 0:
        detail_segments.append(
            (
                "state_avoidable",
                waste.state_machine_avoidable_ms,
                "Django state (avoidable mig)",
                _WASTE_CATEGORY_COLORS["state_avoidable"],
            )
        )

    detail_bar_parts = []
    for _key, ms, label, color in detail_segments:
        pct = ms / apply_total * 100.0
        detail_bar_parts.append(
            f'<div class="waste-seg" style="width:{pct:.2f}%;background:{color}" '
            f'title="{_esc(label)}: {_fmt_ms(ms)} ({pct:.1f}%)"></div>'
        )
    detail_legend_parts = []
    for key, ms, label, color in detail_segments:
        pct = ms / apply_total * 100.0
        is_avoidable = (key in AVOIDABLE_CATEGORIES) or key == "state_avoidable"
        detail_legend_parts.append(
            f'<div class="waste-legend-item">'
            f'<span class="waste-sw" style="background:{color}"></span>'
            f'<span class="waste-legend-label">{_esc(label)}</span>'
            f'<span class="waste-legend-time">{_fmt_ms(ms)} ({pct:.1f}%)</span>'
            f'<span class="waste-legend-verdict {"verdict-avoid" if is_avoidable else "verdict-essential"}">'
            f"{'avoidable' if is_avoidable else 'essential'}</span>"
            "</div>"
        )

    return (
        headline
        + "<h3>Top-level breakdown</h3>"
        + '<div class="waste-bar">'
        + "".join(top_bar_parts)
        + "</div>"
        + '<div class="waste-legend">'
        + "".join(top_legend_parts)
        + "</div>"
        + "<h3>Per-category breakdown</h3>"
        + '<div class="waste-bar">'
        + "".join(detail_bar_parts)
        + "</div>"
        + '<div class="waste-legend">'
        + "".join(detail_legend_parts)
        + "</div>"
    )


def _html_findings(findings: list[Finding]) -> str:
    """Render AST-detected dead code grouped by detector + confidence."""
    by_detector: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_detector[f.detector_name].append(f)
    parts: list[str] = []
    for detector_name, hits in sorted(by_detector.items(), key=lambda kv: -len(kv[1])):
        parts.append(f"<h3>{_esc(detector_name)} <span class='muted'>({len(hits)} hits)</span></h3>")
        tier_counts: dict[str, int] = defaultdict(int)
        for f in hits:
            tier_counts[f.confidence_tier.value] += 1
        chips = []
        for tier in ("high", "medium", "low"):
            n = tier_counts.get(tier, 0)
            if n:
                chips.append(
                    f"<span class='pill ease-{ {'high': 'easy', 'medium': 'medium', 'low': 'hard'}[tier] }'>{n} {tier}</span>"
                )
        if chips:
            parts.append("<p>" + " ".join(chips) + "</p>")
        rows = []
        for f in sorted(hits, key=lambda x: -x.confidence)[:50]:
            migs = ", ".join(f"<code>{_esc(a)}.{_esc(n)}</code>" for a, n in f.migrations[:3])
            if len(f.migrations) > 3:
                migs += f" <span class='muted'>(+{len(f.migrations) - 3} more)</span>"
            rows.append(
                "<tr>"
                f"<td><span class='pill ease-{ {'high': 'easy', 'medium': 'medium', 'low': 'hard'}[f.confidence_tier.value] }'>{f.confidence_tier.value}</span></td>"
                f"<td>{_esc(f.summary)}</td>"
                f"<td>{migs}</td>"
                f"<td><details><summary>view</summary><pre>{_esc(f.detail)}</pre></details></td>"
                "</tr>"
            )
        parts.append(
            '<table class="sortable"><thead><tr>'
            "<th>Confidence</th><th>Finding</th><th>Migrations</th><th>Detail</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
    return "".join(parts)


def _html_useless_runpython(runs: list[ProfileRun]) -> str:
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
            categorized[_classify_runpython(op)].append(op)

    total = sum(len(v) for v in categorized.values())
    if total == 0:
        return '<p class="muted"><em>no RunPython operations recorded</em></p>'
    wasted = sum(op["duration_ms"] for k in ("inert", "read-only-empty") for op in categorized[k])
    candidate_count = len(categorized["inert"]) + len(categorized["read-only-empty"])

    descriptions = {
        "active": "ran INSERT/UPDATE/DELETE — real work",
        "read-only-empty": "ran only SELECTs, all &lt;5ms total — looked for rows, found none",
        "read-only": "ran only SELECTs, ≥5ms total — may branch on results",
        "inert": "ran no SQL at all — pure no-op",
    }
    breakdown_rows = []
    max_total = (
        max(
            (sum(op["duration_ms"] for op in categorized[k]) for k in categorized),
            default=1.0,
        )
        or 1.0
    )
    for kind in ("active", "read-only", "read-only-empty", "inert"):
        ops = categorized[kind]
        total_ms = sum(op["duration_ms"] for op in ops)
        breakdown_rows.append(
            f"<tr>"
            f"<td><strong>{_esc(kind)}</strong></td>"
            f"<td class='num'>{len(ops)}</td>"
            f"{_bar_cell(total_ms, max_total)}"
            f"<td class='muted'>{descriptions[kind]}</td>"
            f"</tr>"
        )

    candidates = [(op, kind) for kind in ("inert", "read-only-empty") for op in categorized[kind]]
    candidates.sort(key=lambda x: -x[0]["duration_ms"])

    candidate_rows = []
    max_d = candidates[0][0]["duration_ms"] if candidates else 1.0
    for op, kind in candidates[:50]:
        callable_name = (op.get("metadata") or {}).get("callable", "?")
        candidate_rows.append(
            f"<tr>"
            f"<td>{_esc(op['database'])}</td>"
            f"<td>{_esc(op['app_label'])}</td>"
            f"<td><code>{_esc(op['migration_name'])}</code></td>"
            f"<td>{_esc(kind)}</td>"
            f"{_bar_cell(op['duration_ms'], max_d)}"
            f"<td class='num'>{op.get('sql_count', 0)}</td>"
            f"<td><code>{_esc(str(callable_name)[:60])}</code></td>"
            f"</tr>"
        )

    lead = (
        f'<p class="section-lead"><strong>{candidate_count} of {total} RunPython operations</strong> '
        f"did nothing observable to the database on this fresh-DB run, costing <strong>"
        f"{_fmt_ms(wasted)}</strong> in pure overhead. Most are likely "
        "2-year-old backfills / corruption fixes whose target rows never existed on a fresh "
        "database. Safest squash candidates after a per-migration audit.</p>"
    )

    breakdown_table = (
        '<table class="sortable"><thead><tr>'
        "<th>Class</th><th>Count</th><th>Total DB time</th><th>Interpretation</th>"
        "</tr></thead><tbody>" + "".join(breakdown_rows) + "</tbody></table>"
    )
    candidate_table = (
        '<table class="sortable"><thead><tr>'
        "<th>DB</th><th>App</th><th>Migration</th><th>Class</th><th>Duration</th><th>SQL count</th><th>Callable</th>"
        "</tr></thead><tbody>" + "".join(candidate_rows) + "</tbody></table>"
    )

    return lead + breakdown_table + "<h3>Slowest no-op RunPython ops (top 50)</h3>" + candidate_table


def _html_squash_impact(runs: list[ProfileRun]) -> str:
    sql_by_mig: dict[tuple[str, str, str], float] = defaultdict(float)
    for run in runs:
        for op in _effective_ops(run.ops):
            sql_by_mig[(run.database, op["app_label"], op["migration_name"])] += op["duration_ms"]

    per_app: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "apply_ms": 0.0})
    grand_count = 0
    grand_apply = 0.0
    for run in runs:
        for (app, name), apply_ms in run.migration_summaries.items():
            if sql_by_mig.get((run.database, app, name), 0.0) > LOW_SQL_THRESHOLD_MS:
                continue
            per_app[app]["count"] += 1
            per_app[app]["apply_ms"] += apply_ms
            grand_count += 1
            grand_apply += apply_ms

    if grand_count == 0:
        return '<p class="muted"><em>no low-SQL migrations found</em></p>'

    items = sorted(per_app.items(), key=lambda x: -x[1]["apply_ms"])
    max_apply = items[0][1]["apply_ms"] if items else 1.0
    rows_html = []
    for app, stats in items:
        n = int(stats["count"])
        apply_ms = stats["apply_ms"]
        avg = apply_ms / n if n else 0.0
        saved = apply_ms * (n - 1) / n if n > 0 else 0.0
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(app)}</td>"
            f"<td class='num'>{n}</td>"
            f"{_bar_cell(apply_ms, max_apply)}"
            f"<td class='num' data-sort='{avg:.3f}'>{_fmt_ms(avg)}</td>"
            f"<td class='num' data-sort='{saved:.3f}'>{_fmt_ms(saved)}</td>"
            f"</tr>"
        )
    lead = (
        f'<p class="section-lead">Found <strong>{grand_count} migrations</strong> with '
        f"≤{LOW_SQL_THRESHOLD_MS:.0f}ms of SQL work, totalling "
        f"<strong>{_fmt_ms(grand_apply)}</strong> of <code>Migration.apply</code> time. "
        "These are the strongest squash ROI — the cost is almost entirely Python.</p>"
    )
    return (
        lead + '<table class="sortable"><thead><tr>'
        "<th>App</th><th>Low-SQL migrations</th><th>Apply total</th><th>Avg per migration</th><th>Est. savings if folded</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_squash_clusters(runs: list[ProfileRun]) -> str:
    CLUSTER_MAX_MS = 200.0
    MIN_CLUSTER_SIZE = 5
    by_app: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for run in runs:
        for (app, name), apply_ms in run.migration_summaries.items():
            by_app[(run.database, app)].append((name, apply_ms))
    clusters = []
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
            if j - i >= MIN_CLUSTER_SIZE:
                clusters.append((db, app, pairs[i][0], pairs[j - 1][0], j - i, total))
            i = j

    if not clusters:
        return f'<p class="muted"><em>no clusters of {MIN_CLUSTER_SIZE}+ low-cost migrations found</em></p>'

    clusters.sort(key=lambda c: -c[5])
    max_total = clusters[0][5]
    rows_html = []
    for db, app, first, last, count, total in clusters[:30]:
        saved = total * (count - 1) / count
        rows_html.append(
            f"<tr>"
            f"<td>{_esc(db)}</td>"
            f"<td>{_esc(app)}</td>"
            f"<td><code>{_esc(first)}</code></td>"
            f"<td><code>{_esc(last)}</code></td>"
            f"<td class='num'>{count}</td>"
            f"{_bar_cell(total, max_total)}"
            f"<td class='num' data-sort='{saved:.3f}'>{_fmt_ms(saved)}</td>"
            f"</tr>"
        )
    lead = (
        f'<p class="section-lead">Runs of {MIN_CLUSTER_SIZE}+ consecutive migrations '
        f"in the same app, each &lt;{CLUSTER_MAX_MS:.0f}ms of <code>Migration.apply</code>. "
        "These are concrete batched-squash targets — fold the range into one.</p>"
    )
    return (
        lead + '<table class="sortable"><thead><tr>'
        "<th>DB</th><th>App</th><th>From</th><th>To</th><th>Count</th><th>Cluster total</th><th>Est. savings if folded</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


def _html_table_py(rows: list[tuple[str, float, float]], time_col: str) -> str:
    max_v = rows[0][1] if rows else 1.0
    rows_html = []
    for fn, t, p in rows[:TOP_PY_FUNCS]:
        rows_html.append(
            f"<tr>"
            f"<td><code>{_esc(fn)}</code></td>"
            f"{_bar_cell(t, max_v, f'{t:.2f}s')}"
            f"<td class='num' data-sort='{p:.2f}'>{p:.1f}%</td>"
            f"</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        f"<th>Function</th><th>{_esc(time_col)}</th><th>% of total</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )


# Silence unused-import linters: _build_children_index is re-exported for tests.
__all__ = ["render_html_report"]
_ = _build_children_index
