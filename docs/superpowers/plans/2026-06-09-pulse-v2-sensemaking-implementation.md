# Pulse v2: Sense-making on scout anomalies — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pulse consume the Signals anomaly-detection scout's findings (behind a pluggable `AnomalySource` interface, scout-only in v1) instead of running its own detection, then run Pulse's existing causal-enrichment + Max handoff on top.

**Architecture:** Introduce `AnomalySource.get_findings(...) -> list[Finding]` at the `Finding` boundary in `products/pulse/backend/temporal/workflow.py`, replacing `select_candidate_metrics_activity → detect_changes_activity`. The one v1 implementation, `ScoutAnomalySource`, calls a new `get_team_anomalies` read method on the Signals facade (reads raw anomaly signals from ClickHouse `document_embeddings`), then adapts each into a `Finding` by best-effort-extracting the flagged insight `short_id` from `evidence[].entity_id`, loading the insight, and re-scoring it (numbers only, no re-gate). Everything downstream of `Finding` (enrich/narrative/synthesis/Max) is unchanged.

**Tech Stack:** Django, Temporal (pydantic activities), HogQL/ClickHouse (`execute_hogql_query_with_retry`), `products/signals` facade, pulse `detection.py`/`types.py`, kea + Max side panel (Phase 2).

**Spec:** `docs/superpowers/specs/2026-06-09-pulse-sensemaking-on-scout-anomalies-design.md`

**Stacking note:** this branch (`vdekrijger-pulse-v2-sensemaking`) is off the round-1 extraction stack tip (`vdekrijger-pulse-frontend`), because `products/pulse` only exists there, not on master. Rebase onto master once round-1 (#62116–62120) merges. Phase 1 = backend source-swap (PR1); Phase 2 = proactive surfacing (PR2).

**Verify commands** (this repo): backend `flox activate -- bash -c "python -m pytest <path> -q --no-header -p no:cacheprovider --reuse-db"`; ruff `flox activate -- bash -c "ruff check <path> && ruff format <path>"`; FE jest `flox activate -- bash -c "pnpm --filter=@posthog/frontend exec jest <path>"`.

---

## File Structure

**Phase 1 (PR1 — backend source-swap):**
- Modify `products/pulse/backend/temporal/detection.py` — extract `score_series()` + `_build_finding()` (no-gate scoring), keep `_evaluate_candidate` gating.
- Create `products/pulse/backend/temporal/sources.py` — `AnomalySource` protocol + `ScoutAnomalySource` + the scout-signal→`Finding` adapter.
- Modify `products/pulse/backend/temporal/types.py` — add `FetchScoutFindingsInputs`; `AnomalyFinding` DTO lives in the signals facade contract (imported), `Finding` reused.
- Modify `products/pulse/backend/temporal/metrics.py` — add `increment_scout_anomaly_outcome()` counter (resolved / unresolvable_insight / no_series).
- Modify `products/pulse/backend/temporal/workflow.py` — replace `select_candidate_metrics_activity`+`detect_changes_activity` calls with one `fetch_scout_findings_activity`.
- Modify `products/pulse/backend/temporal/__init__.py` + `posthog/temporal/ai/__init__.py` — register `fetch_scout_findings_activity`, drop the two removed activities from registration.
- Create `products/signals/backend/facade/api.py` addition — `get_team_anomalies()` read method (+ `AnomalyFinding` DTO in `products/signals/backend/facade/contracts.py` or inline dataclass).
- Create `products/signals/backend/temporal/signal_queries.py` addition — `fetch_team_anomaly_signals()` ClickHouse read (or co-locate in facade if no Temporal-activity wrapper needed).
- Tests: `products/pulse/backend/tests/temporal/test_sources.py`, `test_pulse_detectors.py` (score_series), `test_pulse_workflow.py` (scout-source path); `products/signals/backend/tests/test_get_team_anomalies.py`.

**Phase 2 (PR2 — proactive surfacing, frontend):**
- Modify `frontend/src/scenes/max/maxContextLogic.ts` — accept a `PulseFindingContext` (full `EnrichedFinding`) alongside the insight context.
- Modify `products/pulse/frontend/Pulse.tsx` + `products/pulse/frontend/utils.ts` — pass full finding context to Max; proactive `suggestedNextStep`; one-click "make this insight" (Max `create_insight`).
- Tests: `products/pulse/frontend/utils.test.ts`, `pulseLogic.test.ts`.

---

## Phase 1 — PR1: Backend source-swap

### Task 1: Extract no-gate scoring in detection.py

**Files:**
- Modify: `products/pulse/backend/temporal/detection.py`
- Test: `products/pulse/backend/tests/temporal/test_pulse_detectors.py`

- [ ] **Step 1: Write the failing test** (append to `test_pulse_detectors.py`)

```python
class TestScoreSeries:
    def test_scores_without_gating(self):
        # A change BELOW min_change_pct: _evaluate_candidate would drop it (gate),
        # but score_series must still return the computed numbers (no gate).
        from products.pulse.backend.temporal.detection import score_series

        config = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)
        # 4 baseline weeks ~100, current ~105 (+5%, below the 25% gate), + a trailing partial week
        scored = score_series([100.0, 101.0, 99.0, 100.0, 105.0, 0.0], config)
        assert scored is not None
        result, current, series = scored
        assert current == 105.0
        assert result.triggered is False  # below gate, but still returned
        assert round(result.change_pct, 3) == 0.05
        assert len(series) == config.baseline_weeks + 1

    def test_returns_none_on_insufficient_data(self):
        from products.pulse.backend.temporal.detection import score_series

        config = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)
        assert score_series([1.0, 2.0], config) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_pulse_detectors.py::TestScoreSeries -q --no-header -p no:cacheprovider"`
Expected: FAIL — `ImportError: cannot import name 'score_series'`.

- [ ] **Step 3: Refactor `_evaluate_candidate` to use the extracted helpers**

In `detection.py`, replace the body of `_evaluate_candidate` and add the two helpers above it:

```python
def score_series(
    weekly_values: list[float], config: PulseScanConfig, detection_mode: str = "change_v1"
) -> tuple[DetectionResult, float, list[float]] | None:
    """Compute the change-detection result for a weekly series WITHOUT applying the trigger gate.

    Returns (result, current_value, sparkline_series) or None when there's too little data. Callers
    that want the detection gate check `result.triggered`; callers that already know the metric is
    anomalous (the scout source) ignore it and use the numbers for display.
    """
    assert config.baseline_weeks is not None
    assert config.min_change_pct is not None
    assert config.robust_z_threshold is not None
    assert config.min_baseline_value is not None
    if len(weekly_values) < MIN_BASELINE_WEEKS + 2:
        return None
    completed = weekly_values[:-1]  # drop the in-progress (partial) week
    current = completed[-1]
    baseline = completed[:-1][-config.baseline_weeks :]
    if len(baseline) < MIN_BASELINE_WEEKS:
        return None
    result = get_detector(detection_mode).detect(
        current, baseline, config.min_change_pct, config.robust_z_threshold, config.min_baseline_value
    )
    series = [float(v) for v in completed[-(config.baseline_weeks + 1) :]]
    return result, current, series


def _build_finding(descriptor: MetricDescriptor, result: DetectionResult, current: float, series: list[float]) -> Finding:
    return Finding(
        descriptor=descriptor,
        current_value=current,
        baseline_value=result.baseline_median,
        change_pct=result.change_pct,
        impact=result.impact,
        robust_z=result.robust_z,
        series=series,
    )
```

Then rewrite `_evaluate_candidate`:

```python
def _evaluate_candidate(
    candidate: CandidateMetric,
    weekly_values: list[float],
    config: PulseScanConfig,
    detection_mode: str = "change_v1",
) -> Finding | None:
    scored = score_series(weekly_values, config, detection_mode)
    if scored is None:
        return None
    result, current, series = scored
    if not result.triggered:
        return None
    return _build_finding(candidate.descriptor, result, current, series)
```

Add `MetricDescriptor` to the existing `from products.pulse.backend.temporal.types import ...` import if not already present.

- [ ] **Step 4: Run to verify it passes** (new test + the existing detector suite, to prove the refactor is behavior-preserving)

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_pulse_detectors.py -q --no-header -p no:cacheprovider"`
Expected: PASS (all existing tests + `TestScoreSeries`).

- [ ] **Step 5: ruff + commit**

```bash
flox activate -- bash -c "ruff check --fix products/pulse/backend/temporal/detection.py products/pulse/backend/tests/temporal/test_pulse_detectors.py && ruff format products/pulse/backend/temporal/detection.py products/pulse/backend/tests/temporal/test_pulse_detectors.py"
git add products/pulse/backend/temporal/detection.py products/pulse/backend/tests/temporal/test_pulse_detectors.py
git commit -m "refactor(pulse): extract no-gate score_series from _evaluate_candidate"
```

---

### Task 2: `get_team_anomalies` read method on the Signals facade

**Files:**
- Modify: `products/signals/backend/facade/api.py` (add `get_team_anomalies` + `AnomalyFinding` dataclass)
- Modify: `products/signals/backend/temporal/signal_queries.py` (add `fetch_team_anomaly_signal_rows`)
- Test: `products/signals/backend/tests/test_get_team_anomalies.py`

**Contract recap (verified):** raw signals live in ClickHouse `document_embeddings` (`product='signals'`, `document_type='signal'`), deduped by `argMax(metadata, inserted_at) GROUP BY document_id`. `metadata` is a JSON string with `source_product`, `source_type`, `weight`, `deleted`, and `extra` (a `SignalsScoutSignalExtra`: `skill_name`, `confidence`, `evidence: [{source_product, summary, entity_id?}]`, `hypothesis?`, `severity?`, `time_range? {date_from,date_to}`, `finding_id`, `scout_run_id`). Scope = `source_product='signals_scout' AND source_type='cross_source_issue'` (ClickHouse) then `extra.skill_name == 'signals-scout-anomaly-detection'` (Python). The flagged insight `short_id` is best-effort: the `entity_id` of the `evidence` entry whose `source_product == 'query_runs'`.

- [ ] **Step 1: Write the failing test**

```python
# products/signals/backend/tests/test_get_team_anomalies.py
import json
from unittest.mock import patch

from posthog.test.base import BaseTest

from products.signals.backend.facade.api import AnomalyFinding, get_team_anomalies

ANOMALY_SKILL = "signals-scout-anomaly-detection"


def _signal_row(skill_name=ANOMALY_SKILL, short_id="abc123", with_short_id=True):
    evidence = [{"source_product": "query_runs", "summary": "spike", **({"entity_id": short_id} if with_short_id else {})}]
    metadata = {
        "source_product": "signals_scout",
        "source_type": "cross_source_issue",
        "weight": 0.86,
        "deleted": False,
        "extra": {
            "skill_name": skill_name,
            "skill_version": 1.0,
            "confidence": 0.9,
            "finding_id": "f1",
            "scout_run_id": "r1",
            "task_run_id": "t1",
            "evidence": evidence,
            "hypothesis": "Likely a deploy regression.",
            "severity": "P1",
            "time_range": {"date_from": "2026-06-01T00:00:00Z", "date_to": "2026-06-08T00:00:00Z"},
        },
    }
    return ("doc-1", "Signups dropped 60%.", json.dumps(metadata), "2026-06-07T00:00:00Z")


class TestGetTeamAnomalies(BaseTest):
    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows")
    def test_parses_and_scopes_to_anomaly_scout(self, mock_rows):
        mock_rows.return_value = [
            _signal_row(),
            _signal_row(skill_name="signals-scout-logs"),  # other scout — must be filtered out
        ]
        out = get_team_anomalies(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert len(out) == 1
        a = out[0]
        assert isinstance(a, AnomalyFinding)
        assert a.insight_short_id == "abc123"
        assert a.weight == 0.86
        assert a.hypothesis == "Likely a deploy regression."
        assert a.severity == "P1"
        assert a.time_range == ("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")

    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows")
    def test_short_id_none_when_no_query_runs_evidence(self, mock_rows):
        mock_rows.return_value = [_signal_row(with_short_id=False)]
        out = get_team_anomalies(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert len(out) == 1
        assert out[0].insight_short_id is None  # adapter will count + skip these
```

- [ ] **Step 2: Run to verify it fails**

Run: `flox activate -- bash -c "python -m pytest products/signals/backend/tests/test_get_team_anomalies.py -q --no-header -p no:cacheprovider"`
Expected: FAIL — `ImportError: cannot import name 'AnomalyFinding'`.

- [ ] **Step 3: Add the ClickHouse read** in `signal_queries.py`

Mirror the existing deduped-read helpers. Add:

```python
def fetch_team_anomaly_signal_rows(team: "Team", date_from: str, date_to: str) -> list[tuple]:
    """Raw scout signals for a team in [date_from, date_to], deduped, not deleted.

    Scoped to source_product='signals_scout'; skill-level scoping (anomaly-detection only) is applied
    by the caller against the parsed `extra.skill_name`. Returns (document_id, content, metadata_json, timestamp).
    """
    query = f"""
        SELECT document_id, content, metadata, timestamp
        FROM ({_deduped_signals_subquery(extra_where="team_id = {team_id} AND timestamp >= {date_from} AND timestamp <= {date_to}")})
        WHERE JSONExtractString(metadata, 'source_product') = 'signals_scout'
          AND JSONExtractString(metadata, 'source_type') = 'cross_source_issue'
          AND NOT JSONExtractBool(metadata, 'deleted')
        ORDER BY timestamp ASC
    """
    result = execute_hogql_query_with_retry(
        query_type="SignalsFetchTeamAnomalies",
        query=query,
        team=team,
        placeholders={
            "team_id": ast.Constant(value=team.id),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        },
    )
    return list(result.results or [])
```

> NOTE for implementer: confirm the exact name/signature of `_deduped_signals_subquery` and the `model_name` placeholder requirement by reading `signal_queries.py:44-66` — the existing read helpers show whether `model_name` must be passed. Match them verbatim; adjust the subquery call to the real helper name.

- [ ] **Step 4: Add `AnomalyFinding` + `get_team_anomalies`** in `facade/api.py`

```python
from dataclasses import dataclass

from products.signals.backend.temporal.signal_queries import fetch_team_anomaly_signal_rows

ANOMALY_DETECTION_SKILL = "signals-scout-anomaly-detection"


@dataclass(frozen=True)
class AnomalyFinding:
    """A single anomaly the scout surfaced, flattened for cross-product (Pulse) consumption.

    insight_short_id is best-effort: the scout is instructed (emit-contract) to put it in the
    evidence entry whose source_product == 'query_runs', but the field is LLM-authored and optional,
    so it can be None — the consumer counts + skips those.
    """

    insight_short_id: str | None
    weight: float
    confidence: float
    hypothesis: str | None
    severity: str | None
    description: str
    time_range: tuple[str, str] | None
    finding_id: str
    scout_run_id: str


def _short_id_from_evidence(evidence: list[dict]) -> str | None:
    for entry in evidence:
        if entry.get("source_product") == "query_runs" and entry.get("entity_id"):
            return str(entry["entity_id"])
    return None


def get_team_anomalies(team: "Team", period_start: str, period_end: str) -> list[AnomalyFinding]:
    """The team's anomaly-detection scout findings in [period_start, period_end].

    Reads raw signals from ClickHouse (NOT grouped reports), scopes to the anomaly-detection scout,
    and flattens each into an AnomalyFinding. Returns [] when the org hasn't approved AI data
    processing (mirrors emit_signal's gate)."""
    organization = team.organization
    if not organization.is_ai_data_processing_approved:
        return []

    rows = fetch_team_anomaly_signal_rows(team, period_start, period_end)
    out: list[AnomalyFinding] = []
    for _document_id, content, metadata_json, _timestamp in rows:
        metadata = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
        extra = metadata.get("extra") or {}
        if extra.get("skill_name") != ANOMALY_DETECTION_SKILL:
            continue
        time_range = extra.get("time_range")
        out.append(
            AnomalyFinding(
                insight_short_id=_short_id_from_evidence(extra.get("evidence") or []),
                weight=float(metadata.get("weight") or 0.0),
                confidence=float(extra.get("confidence") or 0.0),
                hypothesis=extra.get("hypothesis"),
                severity=extra.get("severity"),
                description=content or "",
                time_range=(time_range["date_from"], time_range["date_to"]) if time_range else None,
                finding_id=extra.get("finding_id") or "",
                scout_run_id=extra.get("scout_run_id") or "",
            )
        )
    return out
```

Add `import json` at module top if absent.

- [ ] **Step 5: Run to verify it passes**

Run: `flox activate -- bash -c "python -m pytest products/signals/backend/tests/test_get_team_anomalies.py -q --no-header -p no:cacheprovider --reuse-db"`
Expected: PASS (2 tests).

- [ ] **Step 6: ruff + tach + commit**

```bash
flox activate -- bash -c "ruff check --fix products/signals/backend/facade/api.py products/signals/backend/temporal/signal_queries.py products/signals/backend/tests/test_get_team_anomalies.py && ruff format products/signals/backend/facade/api.py products/signals/backend/temporal/signal_queries.py products/signals/backend/tests/test_get_team_anomalies.py && tach check"
git add products/signals/backend/facade/api.py products/signals/backend/temporal/signal_queries.py products/signals/backend/tests/test_get_team_anomalies.py
git commit -m "feat(signals): add get_team_anomalies facade read for cross-product consumption"
```

---

### Task 3: Scout-anomaly → `Finding` adapter

**Files:**
- Create: `products/pulse/backend/temporal/sources.py`
- Modify: `products/pulse/backend/temporal/metrics.py` (counter)
- Test: `products/pulse/backend/tests/temporal/test_sources.py`

- [ ] **Step 1: Add the counter** in `metrics.py` (mirror existing `increment_detection_outcome`)

```python
def increment_scout_anomaly_outcome(outcome: str, *, count: int = 1) -> None:
    """Per-anomaly adapter outcomes: resolved / unresolvable_insight / no_series.

    `unresolvable_insight` measures how often the scout's best-effort short_id is missing or doesn't
    load — the signal that the scout emit contract should be hardened (spec D5/O-followup)."""
    meter = _meter({"outcome": outcome})
    if meter is None:
        return
    meter.create_counter("pulse_scout_anomaly_outcome", "Pulse scout-anomaly adapter outcomes").add(count)
```

- [ ] **Step 2: Write the failing test** for the adapter

```python
# products/pulse/backend/tests/temporal/test_sources.py
import pytest
from unittest.mock import patch

from posthog.test.base import BaseTest
from posthog.schema import PulseScanConfig

from products.pulse.backend.temporal.sources import _adapt_anomaly_to_finding
from products.signals.backend.facade.api import AnomalyFinding

SOURCES = "products.pulse.backend.temporal.sources"
RESOLVED_CONFIG = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)


def _anomaly(short_id="abc123"):
    return AnomalyFinding(
        insight_short_id=short_id, weight=0.86, confidence=0.9, hypothesis="deploy regression",
        severity="P1", description="Signups dropped.", time_range=("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z"),
        finding_id="f1", scout_run_id="r1",
    )


class TestAdaptAnomalyToFinding(BaseTest):
    @pytest.mark.asyncio
    async def test_none_when_no_short_id(self):
        with patch(f"{SOURCES}.increment_scout_anomaly_outcome") as counter:
            result = await _adapt_anomaly_to_finding(self.team, _anomaly(short_id=None), RESOLVED_CONFIG)
        assert result is None
        counter.assert_called_once_with("unresolvable_insight")

    @pytest.mark.asyncio
    async def test_none_when_insight_missing(self):
        with patch(f"{SOURCES}.increment_scout_anomaly_outcome") as counter:
            result = await _adapt_anomaly_to_finding(self.team, _anomaly(short_id="missing"), RESOLVED_CONFIG)
        assert result is None
        counter.assert_called_once_with("unresolvable_insight")

    @pytest.mark.asyncio
    async def test_builds_finding_without_regating(self):
        # Insight whose weekly series moves only +5% (below the 25% gate) must STILL yield a Finding
        # (the scout already decided it's anomalous; Pulse re-scores for display only).
        from products.product_analytics.backend.models.insight import Insight
        from posthog.models.scoping import team_scope

        with team_scope(self.team.id):
            insight = Insight.objects.create(
                team=self.team, name="Signups",
                query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "signup", "math": "total"}]},
            )
        with (
            patch(f"{SOURCES}.run_trends_query_sync", return_value={"results": [{"data": [100.0, 101.0, 99.0, 100.0, 105.0, 0.0]}]}),
            patch(f"{SOURCES}.increment_scout_anomaly_outcome") as counter,
        ):
            result = await _adapt_anomaly_to_finding(self.team, _anomaly(short_id=insight.short_id), RESOLVED_CONFIG)
        assert result is not None
        assert result.descriptor.source == "scout_anomaly"
        assert result.current_value == 105.0
        assert round(result.change_pct, 3) == 0.05  # below gate, but produced anyway
        counter.assert_called_once_with("resolved")
```

- [ ] **Step 3: Run to verify it fails**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_sources.py -q --no-header -p no:cacheprovider --reuse-db"`
Expected: FAIL — `ModuleNotFoundError: products.pulse.backend.temporal.sources`.

- [ ] **Step 4: Implement the adapter** in `sources.py`

```python
"""Anomaly sources for Pulse: where the findings to enrich come from.

v1 ships exactly one source — ScoutAnomalySource — which consumes the Signals anomaly-detection
scout (behind the AnomalySource protocol so a deterministic source can be added later without
touching anything downstream of Finding).
"""

from typing import Protocol

import structlog

from posthog.schema import PulseScanConfig

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.pulse.backend.temporal.detection import _build_finding, score_series
from products.pulse.backend.temporal.metrics import increment_scout_anomaly_outcome
from products.pulse.backend.temporal.types import CandidateMetric, Finding, MetricDescriptor, run_trends_query_sync

logger = structlog.get_logger(__name__)


class AnomalySource(Protocol):
    async def get_findings(self, team_id: int, period_start: str, period_end: str, config: PulseScanConfig) -> list[Finding]:
        ...


def _to_trends_query(query: object) -> dict | None:
    """Unwrap an insight's query down to a TrendsQuery dict, or None if it isn't one."""
    while isinstance(query, dict) and query.get("source"):
        query = query["source"]
    if isinstance(query, dict) and query.get("kind") == "TrendsQuery":
        return query
    return None


async def _adapt_anomaly_to_finding(team: Team, anomaly: "AnomalyFinding", config: PulseScanConfig) -> Finding | None:
    """Best-effort: load the scout-flagged insight by short_id and re-score it for display numbers.

    Does NOT re-gate — the scout already decided this is anomalous, so we always build a Finding when
    the insight + series resolve. Increments a counter so the unresolvable rate is measurable."""
    # Lazy import: pulse is eagerly preloaded via posthog.api; importing product_analytics models at
    # module scope risks an app-init import cycle (matches selection.py / delivery.py).
    from products.product_analytics.backend.models.insight import Insight  # noqa: PLC0415

    if not anomaly.insight_short_id:
        increment_scout_anomaly_outcome("unresolvable_insight")
        return None

    @database_sync_to_async
    def _load() -> "Insight | None":
        return Insight.objects.filter(team=team, short_id=anomaly.insight_short_id, deleted=False).first()

    insight = await _load()
    query = _to_trends_query(insight.query) if insight else None
    if insight is None or query is None:
        increment_scout_anomaly_outcome("unresolvable_insight")
        logger.warning("pulse_scout_anomaly_unresolvable", team_id=team.id, short_id=anomaly.insight_short_id)
        return None

    # detection._build_detection_query mutates dateRange/interval and strips breakdowns.
    from products.pulse.backend.temporal.detection import _build_detection_query, _extract_weekly_series  # noqa: PLC0415

    assert config.baseline_weeks is not None
    try:
        result = await run_trends_query_sync(team, _build_detection_query(query, config.baseline_weeks))
    except Exception as exc:
        increment_scout_anomaly_outcome("no_series")
        logger.warning("pulse_scout_anomaly_query_failed", team_id=team.id, short_id=anomaly.insight_short_id, error=str(exc))
        return None

    series = _extract_weekly_series(result)
    scored = score_series(series, config)
    if scored is None:
        increment_scout_anomaly_outcome("no_series")
        return None

    detection_result, current, sparkline = scored
    descriptor = MetricDescriptor(
        source="scout_anomaly",
        source_id=insight.id,
        label=insight.name or insight.derived_name or f"Insight {insight.short_id}",
        query=query,
        url=f"/insights/{insight.short_id}",
    )
    increment_scout_anomaly_outcome("resolved")
    # Build unconditionally — trust the scout's anomaly decision; re-score only for the numbers.
    return _build_finding(descriptor, detection_result, current, sparkline)
```

(`AnomalyFinding` is type-only here; add `from products.signals.backend.facade.api import AnomalyFinding` under `TYPE_CHECKING` to avoid an import cycle, and quote the annotation as `"AnomalyFinding"`.)

- [ ] **Step 5: Run to verify it passes**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_sources.py -q --no-header -p no:cacheprovider --reuse-db"`
Expected: PASS (3 tests).

- [ ] **Step 6: ruff + commit**

```bash
flox activate -- bash -c "ruff check --fix products/pulse/backend/temporal/sources.py products/pulse/backend/temporal/metrics.py products/pulse/backend/tests/temporal/test_sources.py && ruff format products/pulse/backend/temporal/sources.py products/pulse/backend/temporal/metrics.py products/pulse/backend/tests/temporal/test_sources.py"
git add products/pulse/backend/temporal/sources.py products/pulse/backend/temporal/metrics.py products/pulse/backend/tests/temporal/test_sources.py
git commit -m "feat(pulse): scout-anomaly to Finding adapter (best-effort short_id, no re-gate)"
```

---

### Task 4: `ScoutAnomalySource` + `fetch_scout_findings_activity`

**Files:**
- Modify: `products/pulse/backend/temporal/sources.py` (add `ScoutAnomalySource`)
- Modify: `products/pulse/backend/temporal/types.py` (add `FetchScoutFindingsInputs`)
- Modify: `products/pulse/backend/temporal/workflow.py` (add `fetch_scout_findings_activity`)
- Test: `products/pulse/backend/tests/temporal/test_sources.py`

- [ ] **Step 1: Write the failing test**

```python
class TestScoutAnomalySource(BaseTest):
    @pytest.mark.asyncio
    async def test_maps_anomalies_to_findings_dropping_unresolvable(self):
        from products.pulse.backend.temporal.sources import ScoutAnomalySource

        anomalies = [_anomaly(short_id="resolves"), _anomaly(short_id=None)]
        with (
            patch(f"{SOURCES}.get_team_anomalies", return_value=anomalies),
            patch(f"{SOURCES}._adapt_anomaly_to_finding", side_effect=[object(), None]) as adapt,
        ):
            findings = await ScoutAnomalySource().get_findings(self.team.id, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", RESOLVED_CONFIG)
        assert len(findings) == 1  # the None (unresolvable) is dropped
        assert adapt.call_count == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_sources.py::TestScoutAnomalySource -q --no-header -p no:cacheprovider --reuse-db"`
Expected: FAIL — `ImportError: cannot import name 'ScoutAnomalySource'`.

- [ ] **Step 3: Implement `ScoutAnomalySource`** in `sources.py`

```python
class ScoutAnomalySource:
    """v1 AnomalySource: consume the Signals anomaly-detection scout's findings."""

    async def get_findings(self, team_id: int, period_start: str, period_end: str, config: PulseScanConfig) -> list[Finding]:
        from products.signals.backend.facade.api import get_team_anomalies  # noqa: PLC0415 — facade, avoid app-init cycle

        @database_sync_to_async
        def _fetch() -> tuple[Team, list]:
            team = Team.objects.get(id=team_id)
            return team, get_team_anomalies(team, period_start, period_end)

        team, anomalies = await _fetch()
        findings: list[Finding] = []
        for anomaly in anomalies:
            finding = await _adapt_anomaly_to_finding(team, anomaly, config)
            if finding is not None:
                findings.append(finding)
        return findings
```

- [ ] **Step 4: Add the activity** in `workflow.py` and the input type in `types.py`

`types.py`:

```python
class FetchScoutFindingsInputs(BaseModel):
    team_id: int
    period_start: str
    period_end: str
    config: PulseScanConfig = Field(default_factory=PulseScanConfig)
```

`workflow.py` (new activity near the other `@activity.defn`s):

```python
@activity.defn
async def fetch_scout_findings_activity(inputs: FetchScoutFindingsInputs) -> list[Finding]:
    """v1 anomaly source: consume the Signals anomaly-detection scout, adapt to Findings."""
    return await ScoutAnomalySource().get_findings(
        inputs.team_id, inputs.period_start, inputs.period_end, inputs.config
    )
```

Add imports to `workflow.py`: `from products.pulse.backend.temporal.sources import ScoutAnomalySource` and `FetchScoutFindingsInputs` to the `types` import.

- [ ] **Step 5: Run to verify it passes**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_sources.py -q --no-header -p no:cacheprovider --reuse-db"`
Expected: PASS.

- [ ] **Step 6: ruff + commit**

```bash
flox activate -- bash -c "ruff check --fix products/pulse/backend/temporal/sources.py products/pulse/backend/temporal/types.py products/pulse/backend/temporal/workflow.py products/pulse/backend/tests/temporal/test_sources.py && ruff format products/pulse/backend/temporal/sources.py products/pulse/backend/temporal/types.py products/pulse/backend/temporal/workflow.py products/pulse/backend/tests/temporal/test_sources.py"
git add products/pulse/backend/temporal/sources.py products/pulse/backend/temporal/types.py products/pulse/backend/temporal/workflow.py products/pulse/backend/tests/temporal/test_sources.py
git commit -m "feat(pulse): ScoutAnomalySource + fetch_scout_findings_activity"
```

---

### Task 5: Wire the source into the workflow (replace select+detect)

**Files:**
- Modify: `products/pulse/backend/temporal/workflow.py` (the `run` method)
- Modify: `products/pulse/backend/temporal/__init__.py` + `posthog/temporal/ai/__init__.py` (registration)
- Test: `products/pulse/backend/tests/temporal/test_pulse_workflow.py`

- [ ] **Step 1: Update the workflow test's `_run_scan` helper** — replace the `select_candidate_metrics_activity` + `detect_changes_activity` mocks with one `fetch_scout_findings_activity` mock (returns `findings`). Mirror the existing helper exactly; the activity-name string is `"fetch_scout_findings_activity"`. Keep the no-findings, failure, and with-findings tests; they now drive findings through the new activity.

```python
    @activity.defn(name="fetch_scout_findings_activity")
    async def m_fetch(inputs: object) -> list[Finding]:
        if detect_raises:
            raise RuntimeError("fetch boom")
        return detected
```

Remove the `m_select` / `m_detect` stubs and drop them from the `activities=[...]` list; add `m_fetch`.

- [ ] **Step 2: Run to verify it fails**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_pulse_workflow.py -q --no-header -p no:cacheprovider --reuse-db"`
Expected: FAIL — the workflow still calls `select_candidate_metrics_activity`, which is no longer registered → activity-not-registered error.

- [ ] **Step 3: Replace the select+detect block** in `workflow.py` `run`

Replace the `select_candidate_metrics_activity` + `detect_changes_activity` calls (the block that produces `findings`) with:

```python
            findings = await workflow.execute_activity(
                fetch_scout_findings_activity,
                FetchScoutFindingsInputs(
                    team_id=inputs.team_id,
                    period_start=inputs.period_start,
                    period_end=inputs.period_end,
                    config=config,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
```

Leave the `if not findings:` no-findings branch and everything after (enrich/persist/synthesize/notify/emit) unchanged.

- [ ] **Step 4: Update activity registration**

In `products/pulse/backend/temporal/__init__.py` and `posthog/temporal/ai/__init__.py`: add `fetch_scout_findings_activity`, remove `select_candidate_metrics_activity` and `detect_changes_activity` from the registered activity lists and `__all__`. (Leave `selection.py`/`detection.py` modules in place — they remain the future `DeterministicSource` impl + the adapter uses detection's scoring.)

- [ ] **Step 5: Run to verify it passes**

Run: `flox activate -- bash -c "python -m pytest products/pulse/backend/tests/temporal/test_pulse_workflow.py -q --no-header -p no:cacheprovider --reuse-db"`
Expected: PASS (no-findings → DELIVERED finding_count 0; failure → FAILED; with-findings → DELIVERED finding_count > 0).

- [ ] **Step 6: ruff + commit**

```bash
flox activate -- bash -c "ruff check --fix products/pulse/backend/temporal/workflow.py products/pulse/backend/temporal/__init__.py posthog/temporal/ai/__init__.py products/pulse/backend/tests/temporal/test_pulse_workflow.py && ruff format products/pulse/backend/temporal/workflow.py products/pulse/backend/temporal/__init__.py posthog/temporal/ai/__init__.py products/pulse/backend/tests/temporal/test_pulse_workflow.py"
git add products/pulse/backend/temporal/workflow.py products/pulse/backend/temporal/__init__.py posthog/temporal/ai/__init__.py products/pulse/backend/tests/temporal/test_pulse_workflow.py
git commit -m "feat(pulse): drive scans from the scout anomaly source (v1)"
```

---

### Task 6: Empty-state + sensitivity-config neutralization (D3) + full backend gauntlet

**Files:**
- Modify: `products/pulse/backend/api.py` (the `trigger_scan` config + the `current`/subscription surface — neutralize detection-tuning knobs that the scout now owns; keep the model)
- Modify: `products/pulse/frontend/pulseLogic.ts` / `Pulse.tsx` empty state copy → "Enable the anomaly scout to get a Pulse digest" when the team has no scout enrollment / no anomalies
- Test: `products/pulse/backend/tests/test_api.py`

- [ ] **Step 1:** Decide D3 with the reviewer — for v1, hide the sensitivity/threshold inputs from the subscription UI (they no longer affect detection) but keep the model + serializer fields (no migration). Add a test asserting `trigger_scan`/subscription still works with the knobs ignored. (Full code depends on the D3 choice confirmed in review; if "keep as-is," this task is a no-op + a doc comment on `PulseScanConfig` noting the knobs are display-only in v1.)

- [ ] **Step 2: Full backend gauntlet** (run before opening PR1)

```bash
flox activate -- bash -c "python -m pytest products/pulse/backend/tests/ products/signals/backend/tests/test_get_team_anomalies.py -q --no-header -p no:cacheprovider --create-db && ruff check products/pulse products/signals/backend/facade products/signals/backend/temporal/signal_queries.py && DEBUG=1 python manage.py makemigrations --check --dry-run pulse signals && tach check"
```

Expected: all green, `No changes detected` for migrations (no model changes in PR1), tach validated.

---

## Phase 2 — PR2: Proactive surfacing (frontend)

> Builds on PR1. The causal narrative + chips + `suggestedNextStep` already exist; this phase makes Pulse *drive* the exploration (full Max context + one-click insight) rather than wait for a click.

### Task 7: Pass the full finding context to Max

**Files:**
- Modify: `frontend/src/scenes/max/maxContextLogic.ts` (accept a finding-context payload alongside the insight)
- Modify: `products/pulse/frontend/utils.ts` (`buildMaxSeedPrompt` already exists — extend the context builder to attach narrative + attribution + references)
- Modify: `products/pulse/frontend/Pulse.tsx` (the "Explore with AI" handoff calls the extended context setter)
- Test: `products/pulse/frontend/utils.test.ts`

- [ ] Add a `buildFindingMaxContext(finding)` in `utils.ts` returning `{ insight: InsightWithQuery | null, narrative: string, attribution, references }`; test it returns the narrative + attribution from an `EnrichedFinding`-shaped `PulseFindingType`. Wire `Pulse.tsx`'s handoff to pass it via `maxContextLogic`. Seed prompt references the context so Max continues rather than re-derives. (Jest, mirror `pulseLogic.test.ts` patterns.)

### Task 8: One-click "make this insight" + proactive next-step

**Files:**
- Modify: `products/pulse/frontend/Pulse.tsx` (+ `pulseLogic.ts` if a listener is needed)
- Test: `products/pulse/frontend/pulseLogic.test.ts`

- [ ] Surface `suggestedNextStep(finding)` as a primary action on each finding card (it already exists, deterministic). Add a "Build this insight" action that opens Max seeded to use its `create_insight` tool on the finding's metric. Guard the button against double-submit (`disabledReason`/loading). Test the listener/seed via kea-test, mirroring the existing scan-trigger test.

### Task 9: FE gauntlet

```bash
flox activate -- bash -c "pnpm --filter=@posthog/frontend typegen:write:no-cache && pnpm --filter=@posthog/frontend exec jest products/pulse/frontend && NODE_OPTIONS=--max-old-space-size=8192 pnpm --filter=@posthog/frontend exec tsc --noEmit 2>&1 | grep -ciE 'products/pulse' "
```

Expected: jest green; `0` pulse tsc errors.

---

## Self-review (run after writing; fixes folded in)

**Spec coverage:**
- AnomalySource interface @ Finding boundary → Tasks 4–5. ✅
- v1 scout-only source → Task 4 (`ScoutAnomalySource`), Task 5 (workflow wiring drops select/detect). ✅
- O1 (raw ClickHouse signals) → Task 2 `fetch_team_anomaly_signal_rows`. ✅
- O2 (scope to anomaly-detection scout) → Task 2 (`source_product`/`source_type` in CH + `skill_name` in Python). ✅
- D1 (re-score, no parse) + the no-re-gate refinement → Task 1 (`score_series`), Task 3 (adapter builds unconditionally). ✅
- best-effort short_id (decided) + counter → Task 2 (`_short_id_from_evidence`), Task 3 (`increment_scout_anomaly_outcome`). ✅
- D3 (sensitivity config vestigial) → Task 6. ⚠️ depends on review confirmation — flagged, not silently assumed.
- Reused untouched (narrative/Max) → confirmed: no task modifies `narrative.py`. ✅
- Pillar-4 proactive → Phase 2 (Tasks 7–8). ✅
- Non-goals respected: no Pulse detection in v1 path (selection/detect dropped from activities); no observability-gaps rebuild; no scout emit-contract change (best-effort instead). ✅

**Placeholder scan:** one explicit implementer NOTE in Task 2 Step 3 (confirm the real `_deduped_signals_subquery` name/signature against `signal_queries.py:44-66`) — intentional, because that helper's exact name wasn't verified first-hand; it is a "read X and match verbatim" instruction, not a code placeholder. Task 6 Step 1 is gated on the D3 review decision (called out). No `TBD`/`add error handling`-style gaps.

**Type consistency:** `score_series` returns `(DetectionResult, float, list[float])` used identically in Task 1 and Task 3; `AnomalyFinding` fields defined in Task 2 match the adapter's reads in Task 3; `fetch_scout_findings_activity` name matches the workflow test mock and registration in Task 5.

---

## Execution Handoff

Plan complete. Two execution options:
1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute here with checkpoints.

**Before executing:** the `get_team_anomalies` facade method (Task 2) is the cross-team touch — loop in the Signals team. And confirm the D3 choice (Task 6) and the `_deduped_signals_subquery` helper name (Task 2 NOTE).
