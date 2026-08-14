"""Core logic for `manage.py audit_action_selectors`.

Compares every action selector under the pre-#80653 compiler and the #80653
compiler over real `$autocapture` traffic, buckets each selector by whether the
compiler change moves its match count, and proposes/applies the `>`-to-space
rewrite where measurement shows it is faithful. See the management command for
the CLI surface.
"""

import re
import csv
import json
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models import Team
from posthog.models.event.event import Selector as LiveSelector
from posthog.models.property.util import build_selector_regex as live_build_selector_regex

from products.actions.backend.models.action import Action
from products.actions.backend.selector_audit.compilers import (
    classify_selector,
    compile_new,
    compile_old,
    is_valid_regex,
    rewrite_direct_descendants,
)
from products.product_analytics.backend.models.insight import Insight

BUCKET_UNCHANGED = "unchanged"
BUCKET_GAIN_ONLY = "gain_only"
BUCKET_SAFE_REWRITE = "safe_rewrite"
BUCKET_DEPLOY_DAY_REWRITE = "deploy_day_rewrite"
BUCKET_NO_FAITHFUL_FIX = "no_faithful_fix"
BUCKET_NO_DATA = "no_data"
BUCKET_NOT_MEASURED = "not_measured"
BUCKET_COMPILE_ERROR = "compile_error"

ACTIONABLE_BUCKETS = frozenset({BUCKET_SAFE_REWRITE, BUCKET_DEPLOY_DAY_REWRITE, BUCKET_NO_FAITHFUL_FIX})
COUNT_KEYS = ("old_original", "new_original", "old_rewritten", "new_rewritten")

REPORT_VERSION = 1

# One row per (action, step) selector; JSON-shaped because the report file is
# the source of truth across runs.
Row = dict[str, Any]
Report = dict[str, Any]


def row_key(row: Row) -> str:
    return f"{row['team_id']}:{row['action_id']}:{row['step_index']}:{row['selector']}"


# Synthetic chains that separate the two compilers' combinator semantics: under the
# old compiler `>` reaches past intermediate elements while a bare-tag space must hit
# the immediately-next element; the new compiler inverts both to CSS semantics.
_DEEP_SPAN_CHAIN = 'span.title:nth-child="1";div.wrap:nth-child="2";div:attr_id="root"nth-child="1"'
_DIRECT_SPAN_CHAIN = 'span.title:nth-child="1";div:attr_id="root"nth-child="1"'
_GAPPED_BUTTON_CHAIN = (
    'button.btn:nth-child="1";div.inner:nth-child="1";article.mid:nth-child="1";section.hero:nth-child="1"'
)
_ADJACENT_BUTTON_CHAIN = 'button.btn:nth-child="1";div.inner:nth-child="1";section.hero:nth-child="1"'

_FINGERPRINT_PROBES = (
    ('[id="root"] > span', _DEEP_SPAN_CHAIN),
    ('[id="root"] > span', _DIRECT_SPAN_CHAIN),
    ("section div button", _GAPPED_BUTTON_CHAIN),
    ("section div button", _ADJACENT_BUTTON_CHAIN),
)


def _semantics_fingerprint(compile_fn: Callable[[str], str]) -> tuple[bool, ...]:
    return tuple(bool(re.search(compile_fn(selector), chain)) for selector, chain in _FINGERPRINT_PROBES)


def detect_live_compiler() -> str:
    """Which compiler the running code ships: 'old' (pre-#80653), 'new', or 'unknown'.

    Fingerprints combinator behavior on synthetic chains rather than comparing
    regex strings, so an unrelated compiler tweak (like widening the old tail
    character class) does not flip detection to 'unknown'. 'unknown' means the
    audit's counts may not describe production behavior; writes refuse to run.
    """

    def compile_live(selector: str) -> str:
        return live_build_selector_regex(LiveSelector(selector, escape_slashes=False))

    live = _semantics_fingerprint(compile_live)
    if live == _semantics_fingerprint(compile_old):
        return "old"
    if live == _semantics_fingerprint(compile_new):
        return "new"
    return "unknown"


def discover_rows(team_ids: Optional[list[int]]) -> list[Row]:
    """One row per selector-bearing action step, classification filled in."""
    actions = Action.objects.filter(deleted=False).exclude(steps_json=None)
    if team_ids:
        actions = actions.filter(team_id__in=team_ids)

    rows: list[Row] = []
    for action in actions.order_by("team_id", "id").iterator():
        for step_index, step in enumerate(action.steps):
            selector = (step.selector or "").strip()
            if not selector:
                continue
            classification = classify_selector(selector)
            rewrite = rewrite_direct_descendants(selector)
            compilable = is_valid_regex(compile_old(selector)) and is_valid_regex(compile_new(selector))
            if rewrite != selector:
                compilable = (
                    compilable and is_valid_regex(compile_old(rewrite)) and is_valid_regex(compile_new(rewrite))
                )
            rows.append(
                {
                    "team_id": action.team_id,
                    "action_id": action.id,
                    "action_name": action.name or "",
                    "step_index": step_index,
                    "selector": selector,
                    "rewrite": rewrite if rewrite != selector else None,
                    "structure": classification.structure,
                    "flags": {
                        "nth_child": classification.has_nth_child,
                        "outside_old_allowlist": classification.outside_old_allowlist,
                        "unsupported_css": classification.unsupported_css,
                    },
                    "counts": dict.fromkeys(COUNT_KEYS),
                    "bucket": BUCKET_NOT_MEASURED if compilable else BUCKET_COMPILE_ERROR,
                    "suggestion": None,
                    "references": None,
                    "references_truncated": False,
                    "applied_at": None,
                }
            )
    return rows


def count_autocapture_events(team_id: int, days: int) -> int:
    result = sync_execute(
        """
        SELECT count()
        FROM events
        WHERE team_id = %(team_id)s AND event = '$autocapture' AND timestamp >= %(date_from)s
        """,
        {"team_id": team_id, "date_from": timezone.now() - timedelta(days=days)},
        workload=Workload.OFFLINE,
        team_id=team_id,
        readonly=True,
    )
    return int(result[0][0])


def measure_team_rows(
    team_id: int,
    rows: list[Row],
    days: int,
    batch_size: int,
    sleep_seconds: float,
    log: Callable[[str], object],
) -> None:
    """Fill row counts with countIf(match(elements_chain, regex)) over recent $autocapture."""
    measurable = [row for row in rows if row["bucket"] != BUCKET_COMPILE_ERROR]
    date_from = timezone.now() - timedelta(days=days)

    for batch_start in range(0, len(measurable), batch_size):
        batch = measurable[batch_start : batch_start + batch_size]
        # Identical regexes (same selector on several actions) share one countIf column.
        column_index_by_regex: dict[str, int] = {}
        variants_by_row: list[dict[str, int]] = []
        for row in batch:
            variants: dict[str, int] = {}
            regexes = {
                "old_original": compile_old(row["selector"]),
                "new_original": compile_new(row["selector"]),
            }
            if row["rewrite"]:
                regexes["old_rewritten"] = compile_old(row["rewrite"])
                regexes["new_rewritten"] = compile_new(row["rewrite"])
            for count_key, regex in regexes.items():
                if regex not in column_index_by_regex:
                    column_index_by_regex[regex] = len(column_index_by_regex)
                variants[count_key] = column_index_by_regex[regex]
            variants_by_row.append(variants)

        params: dict[str, Any] = {"team_id": team_id, "date_from": date_from}
        columns: list[str] = []
        for regex, index in column_index_by_regex.items():
            params[f"regex_{index}"] = regex
            columns.append(f"countIf(match(elements_chain, %(regex_{index})s)) AS c_{index}")
        query = f"""
            SELECT {", ".join(columns)}
            FROM events
            WHERE team_id = %(team_id)s AND event = '$autocapture' AND timestamp >= %(date_from)s
        """
        try:
            result = sync_execute(
                query,
                params,
                workload=Workload.OFFLINE,
                team_id=team_id,
                readonly=True,
            )
        except Exception as error:
            # Leave the batch unmeasured rather than aborting the team: the report
            # marks these rows not_measured and a re-run picks them up.
            log(f"  batch failed for team {team_id} ({len(batch)} selectors): {error}")
            continue

        counts_by_column = list(result[0])
        for row, variants in zip(batch, variants_by_row, strict=True):
            for count_key, column in variants.items():
                row["counts"][count_key] = int(counts_by_column[column])
            if not row["rewrite"]:
                # No `>` to rewrite, so the rewrite is the selector itself.
                row["counts"]["old_rewritten"] = row["counts"]["old_original"]
                row["counts"]["new_rewritten"] = row["counts"]["new_original"]
        if sleep_seconds:
            time.sleep(sleep_seconds)


def _close(a: int, b: int, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * max(a, b)


def _faithful(rewritten: int, original: int, tolerance: float, gain_tolerance: float) -> bool:
    """Whether the rewrite's count reproduces the original's within tolerance.

    Loss and gain are bounded separately: the space rewrite of a `>` selector
    matches a superset (any ancestor instead of the old compiler's quirky
    reach), so a small gain is expected and fine, while any loss beyond the
    tolerance means events silently disappear.
    """
    if rewritten < original:
        return original - rewritten <= tolerance * original
    return rewritten - original <= gain_tolerance * max(original, 1)


def decide_bucket(row: Row, tolerance: float, gain_tolerance: float = 0.1) -> None:
    """Assign the decision bucket (and a suggestion for no_faithful_fix rows)."""
    counts = row["counts"]
    if any(counts[key] is None for key in COUNT_KEYS):
        return
    old_original = counts["old_original"]
    new_original = counts["new_original"]
    old_rewritten = counts["old_rewritten"]
    new_rewritten = counts["new_rewritten"]

    if old_original == 0 and new_original == 0:
        row["bucket"] = BUCKET_NO_DATA
    elif _close(old_original, new_original, tolerance):
        row["bucket"] = BUCKET_UNCHANGED
    elif new_original >= old_original:
        row["bucket"] = BUCKET_GAIN_ONLY
    elif _faithful(new_rewritten, old_original, tolerance, gain_tolerance):
        # The rewrite reproduces today's count under the new compiler. If it also
        # changes nothing under the old compiler it can be applied before the
        # deploy; otherwise applying it early would change live matching.
        if _close(old_rewritten, old_original, tolerance):
            row["bucket"] = BUCKET_SAFE_REWRITE
        else:
            row["bucket"] = BUCKET_DEPLOY_DAY_REWRITE
    else:
        row["bucket"] = BUCKET_NO_FAITHFUL_FIX
        candidates = [(row["selector"], new_original)]
        if row["rewrite"]:
            candidates.append((row["rewrite"], new_rewritten))
        closest = min(candidates, key=lambda candidate: abs(candidate[1] - old_original))
        row["suggestion"] = {"selector": closest[0], "new_count": closest[1]}


def collect_references(team: Team, rows: list[Row], log: Callable[[str], object]) -> None:
    """Attach the objects whose behavior a selector change touches to each row."""
    # Imported here to keep DRF (pulled in by the API module) off this module's
    # import path for measurement-only use.
    from products.actions.backend.api.action import find_action_references  # noqa: PLC0415

    action_ids = sorted({row["action_id"] for row in rows})
    actions_by_id = {action.id: action for action in Action.objects.filter(team_id=team.pk, id__in=action_ids)}
    for action_id in action_ids:
        refs = find_action_references(action_id, team)
        truncated = len(refs) >= 50
        references = [{"type": ref["type"], "id": ref["id"], "name": ref["name"], "url": ref["url"]} for ref in refs]

        insight_short_ids = [ref["id"] for ref in references if ref["type"] == "insight"]
        if insight_short_ids:
            # Walked through Insight's reverse relation because tach forbids
            # products.actions importing products.dashboards; the tiles' default
            # manager still excludes deleted tiles and deleted dashboards.
            insights = Insight.objects.filter(team_id=team.pk, short_id__in=insight_short_ids).prefetch_related(
                "dashboard_tiles__dashboard"
            )
            seen_dashboards: set[int] = set()
            for insight in insights:
                for tile in insight.dashboard_tiles.all():
                    dashboard = tile.dashboard
                    if dashboard.pk in seen_dashboards:
                        continue
                    seen_dashboards.add(dashboard.pk)
                    references.append(
                        {
                            "type": "dashboard",
                            "id": str(dashboard.pk),
                            "name": dashboard.name or "Unnamed",
                            "url": f"/dashboard/{dashboard.pk}",
                        }
                    )

        action = actions_by_id.get(action_id)
        if action:
            # Reverse accessor of Survey.actions, reached from the action side
            # because tach forbids products.actions importing products.surveys.
            references.extend(
                {"type": "survey", "id": str(survey.id), "name": survey.name, "url": f"/surveys/{survey.id}"}
                for survey in action.survey_set.filter(team_id=team.pk, archived=False)
            )
        if action and action.post_to_slack:
            references.append(
                {
                    "type": "webhook",
                    "id": str(action_id),
                    "name": "Legacy webhook (post_to_slack)",
                    "url": f"/data-management/actions/{action_id}",
                }
            )

        for row in rows:
            if row["action_id"] == action_id:
                row["references"] = references
                row["references_truncated"] = truncated
    log(f"  collected references for {len(action_ids)} actions")


def build_report(
    rows: list[Row],
    team_totals: dict[int, Optional[int]],
    params: dict[str, Any],
    live_compiler: str,
) -> Report:
    teams: dict[str, Any] = {}
    for row in rows:
        team = teams.setdefault(
            str(row["team_id"]),
            {"autocapture_events": team_totals.get(row["team_id"]), "rows": []},
        )
        team["rows"].append(row)
    return {
        "version": REPORT_VERSION,
        "generated_at": timezone.now().isoformat(),
        "live_compiler": live_compiler,
        "params": params,
        "teams": teams,
    }


def load_report(path: Path) -> Optional[Report]:
    if not path.exists():
        return None
    with open(path) as file:
        return json.load(file)


def iter_report_rows(report: Optional[Report]) -> list[Row]:
    if not report:
        return []
    return [row for team in report["teams"].values() for row in team["rows"]]


def carry_over_previous(rows: list[Row], previous: Optional[Report], keep_measurements: bool) -> None:
    """Keep apply history (and, for discovery-only runs, measurements) across re-runs."""
    previous_by_key = {row_key(row): row for row in iter_report_rows(previous)}
    for row in rows:
        old_row = previous_by_key.get(row_key(row))
        if not old_row:
            continue
        row["applied_at"] = old_row.get("applied_at")
        if keep_measurements and row["bucket"] == BUCKET_NOT_MEASURED:
            row["counts"] = old_row.get("counts", row["counts"])
            row["bucket"] = old_row.get("bucket", row["bucket"])
            row["suggestion"] = old_row.get("suggestion")


def diff_reports(previous: Optional[Report], rows: list[Row]) -> dict[str, list[str]]:
    """Actionable-row movement between runs: fixed, still open, newly actionable."""
    previous_actionable = {
        row_key(row) for row in iter_report_rows(previous) if row.get("bucket") in ACTIONABLE_BUCKETS
    }
    current_by_key = {row_key(row): row for row in rows}
    current_actionable = {key for key, row in current_by_key.items() if row["bucket"] in ACTIONABLE_BUCKETS}
    return {
        "fixed": sorted(previous_actionable - current_actionable),
        "still_open": sorted(previous_actionable & current_actionable),
        "new": sorted(current_actionable - previous_actionable),
    }


def save_report(path: Path, report: Report) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    csv_path = path.with_suffix(".csv")
    with open(csv_path, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "team_id",
                "action_id",
                "action_name",
                "step_index",
                "selector",
                "rewrite",
                "structure",
                "nth_child",
                "outside_old_allowlist",
                "unsupported_css",
                *COUNT_KEYS,
                "bucket",
                "suggested_selector",
                "references",
                "applied_at",
            ]
        )
        for row in iter_report_rows(report):
            writer.writerow(
                [
                    row["team_id"],
                    row["action_id"],
                    row["action_name"],
                    row["step_index"],
                    row["selector"],
                    row["rewrite"] or "",
                    row["structure"],
                    row["flags"]["nth_child"],
                    row["flags"]["outside_old_allowlist"],
                    row["flags"]["unsupported_css"],
                    *[row["counts"][key] if row["counts"][key] is not None else "" for key in COUNT_KEYS],
                    row["bucket"],
                    (row["suggestion"] or {}).get("selector", ""),
                    "|".join(f"{ref['type']}:{ref['id']}" for ref in row["references"] or []),
                    row["applied_at"] or "",
                ]
            )
    return csv_path


def apply_rewrites(
    rows: list[Row], buckets: frozenset[str], live_run: bool, log: Callable[[str], object]
) -> dict[str, int]:
    """Write eligible rewrites back through Action.save() so activity log entries exist."""
    eligible = [row for row in rows if row["bucket"] in buckets and row["rewrite"] and not row["applied_at"]]
    summary = {"applied": 0, "skipped": 0, "planned": 0}
    rows_by_action: dict[tuple[int, int], list[Row]] = {}
    for row in eligible:
        rows_by_action.setdefault((row["team_id"], row["action_id"]), []).append(row)

    for (team_id, action_id), action_rows in sorted(rows_by_action.items()):
        action = Action.objects.filter(team_id=team_id, id=action_id, deleted=False).first()
        if action is None:
            log(f"  skip action {action_id} (team {team_id}): no longer exists")
            summary["skipped"] += len(action_rows)
            continue
        steps = list(action.steps_json or [])
        to_apply: list[Row] = []
        for row in action_rows:
            index = row["step_index"]
            if index >= len(steps) or (steps[index].get("selector") or "").strip() != row["selector"]:
                log(
                    f"  skip action {action_id} step {index} (team {team_id}): "
                    f"selector changed since the report was generated, re-run the audit"
                )
                summary["skipped"] += 1
                continue
            to_apply.append(row)
        if not to_apply:
            continue
        for row in to_apply:
            log(
                f"  {'apply' if live_run else 'would apply'} team {team_id} action {action_id} "
                f"step {row['step_index']}: {row['selector']!r} -> {row['rewrite']!r}"
            )
        if live_run:
            for row in to_apply:
                steps[row["step_index"]]["selector"] = row["rewrite"]
            action.steps_json = steps
            action.save()
            applied_at = timezone.now().isoformat()
            for row in to_apply:
                row["applied_at"] = applied_at
            summary["applied"] += len(to_apply)
        else:
            summary["planned"] += len(to_apply)
    return summary
