# Pulse v2: Sense-making layer on top of scout anomalies — design

**Goal:** Re-center Pulse from "a deterministic anomaly detector that happens to narrate"
to "the analytics co-pilot that takes an anomaly someone else detected and turns it into
understanding + next steps" — proactively driven by Pulse, with Max as the engine underneath.

**Architecture:** Pulse stops discovering anomalies. It consumes anomalies the Signals
anomaly scout already detects (behind a pluggable `AnomalySource` interface), adapts each into
Pulse's existing `Finding` shape, and runs its existing — and genuinely differentiated —
causal-enrichment + guided-exploration pipeline on top, surfaced proactively.

**Tech stack:** Django/Temporal (Pulse backend), `products/signals` facade (read), the existing
Pulse `narrative.py` enrichment + `MaxChatOpenAI`, the Max side panel handoff (`utils.ts`).

---

## Problem / why

Two products were independently doing anomaly detection on the same candidate set (most-viewed
insights) with the same MAD z-score. The Signals anomaly scout is the more capable detector
(seasonality-matched baselines, durable watchlist, explore/exploit memory) and is the system of
record — anomalies it emits flow into the Signals pipeline (group → research → optionally
auto-fix), which is an **engineering-issue-resolution** surface.

Pulse's genuine, non-duplicated value is a different downstream job: **analytics sense-making.**
Given "metric X moved," Pulse answers *why* (the flag flipped / experiment started / segment that
explains it), cross-references what the user isn't tracking yet, and drives a guided exploration
that helps them build the analytics they're missing. That engine already exists in Pulse
(`narrative.py` + the Max handoff) and nothing else in the codebase does it.

So the move is: **demote detection to a consumed input, keep and deepen the sense-making engine.**

## Product positioning (the seat this takes)

- Signals anomaly scout → *detects* anomalies. (engine)
- observability-gaps scout → *finds coverage holes*. (engine)
- **Pulse → "your metric moved: here's why, here's what you're not tracking yet, let's explore it
  and build it together."** Consumes the engines; owns causal correlation + guided exploration.

## v1 scope (decided)

- **`AnomalySource` is the only anomaly entry point**, and v1 ships exactly one implementation:
  `ScoutAnomalySource`. No deterministic detection in the v1 path. The interface exists from day
  one so a `DeterministicSource` (or any other source) can be added later without touching
  anything downstream of `Finding`.
- Pulse v1 only produces digests for teams where the anomaly scout is enrolled and has run.
  Coverage is intentionally bounded — see Risks.

## Architecture

The interface boundary is the existing `Finding` type. Everything downstream of it
(attribution, flag/experiment/annotation correlation, replay evidence, narrative, synthesis,
the Max handoff) already operates on `Finding` / `EnrichedFinding` and does not care where the
anomaly came from — so swapping the source leaves the entire sense-making engine untouched.

```
Signals anomaly scout (detects) ─→ emit_signal ─→ ClickHouse document_embeddings (product='signals')
                                                              │
            products/signals facade: get_team_anomalies(team, time_range)   ← NEW read (raw anomaly signals, O1)
                                                              │
                                              ScoutAnomalySource.get_findings(...)         ← NEW (the only v1 source)
                                                  │  adapt: short_id → insight query,
                                                  │         re-score → Finding numbers,
                                                  │         carry scout hypothesis/severity/weight
                                                  ▼
                                               list[Finding]
                                                  │
   ┌──────────────────────────── UNCHANGED Pulse engine ────────────────────────────┐
   │  enrich_findings: _attribute_finding · correlate flags/experiments/annotations  │
   │  /errors (CoincidentSignal) · replay evidence · _generate_narrative ·           │
   │  synthesize_digest                                                              │
   └─────────────────────────────────────────────────────────────────────────────────┘
                                                  │
                          proactive surface: digest + notify + one-click "make this insight"
                                            + Max-driven suggestedNextStep (full finding context)
```

## Components

### 1. `AnomalySource` interface (NEW)
A small protocol slotted into `workflow.py` where `select_candidate_metrics_activity →
detect_changes_activity` sits today:

```
class AnomalySource(Protocol):
    async def get_findings(self, team_id: int, period_start: str, period_end: str,
                           config: PulseScanConfig) -> list[Finding]: ...
```

v1 wires exactly one implementation. The workflow no longer calls `select` + `detect`; it calls
`source.get_findings(...)` and feeds the result straight into `enrich_findings_activity`.

### 2. `ScoutAnomalySource` (NEW — the only v1 source)
Reads the team's recent raw anomaly signals for the digest period (via the new facade method),
then adapts each into a `Finding`.

### 3. `get_team_anomalies` signals facade read method (NEW)
`products/signals/backend/facade/api.py` is write-only today (`emit_signal` +
`dismiss_report_from_slack`). Add a read method that returns the team's raw anomaly-detection
signals (read from ClickHouse `document_embeddings`, `product='signals'` — O1, NOT grouped
`SignalReport`s) for a time window, as a stable DTO:

```
async def get_team_anomalies(team: Team, period_start: datetime, period_end: datetime
                             ) -> list[AnomalyFinding]
# AnomalyFinding DTO: insight_short_id, time_range, weight, confidence, severity,
#                     hypothesis, description, dedupe_keys, source_run_id
```

Scoped to the anomaly-detection scout's signals (see O2 for the exact key), gated by the same org
`is_ai_data_processing_approved` check `emit_signal` uses. Built as a facade method, **not** a new
REST/HTTP surface, so the boundary stays clean and the signal shape can change without breaking Pulse.

### 4. Anomaly signal → `Finding` adapter (NEW)
For each raw anomaly signal (as an `AnomalyFinding` DTO):
- `insight_short_id` → load the `Insight` → build `MetricDescriptor` (source=`scout_anomaly`,
  label=insight name, query=the saved TrendsQuery, url=`/insights/<short_id>`).
- **Re-score the single flagged insight** with the existing `detection._evaluate_candidate` /
  `_compute_robust_z` to populate `current_value` / `baseline_value` / `change_pct` / `robust_z` /
  `series`. (We re-derive rather than parse the scout's prose numbers — see Decision D1.)
- Carry the scout's `hypothesis` / `severity` / `weight` / `description` along so the narrative LLM
  can build on the scout's prior instead of starting cold.

### 5. Proactive surfacing (NEW behavior on existing surfaces)
Pulse drives the sense-making rather than waiting for a click:
- The digest/notification carries the *why* (already computed), the `suggestedNextStep`, and a
  one-click **"make this insight"** action.
- The Max handoff passes the **full `EnrichedFinding`** (narrative + attribution + coincident
  signals + evidence) as structured context, not just the insight query — so Max continues the
  thread instead of re-reasoning. Max's `create_insight` tool does the actual creation.

### 6. Reused, untouched
The whole `narrative.py` engine and the `utils.ts` / `Pulse.tsx` Max handoff. This is the
differentiator and it does not change shape.

### 7. Deferred (interface-ready, not built in v1)
`DeterministicSource` (today's `selection.py` + `detection.py` discovery path) as a second
`AnomalySource` impl — the path to universal coverage post-v1.

## Key design decisions (recommendations — confirm in review)

- **D1 — Adapter re-scores rather than parses prose.** The scout emits its numbers in prose;
  only the `short_id`, `time_range`, weight/confidence/severity/hypothesis are structured.
  Recommendation: re-score the flagged insight (reuse Pulse's scoring math on one insight). Pros:
  no cross-team emit-contract change; Pulse shows numbers consistent with its own charts. Con:
  Pulse's re-derived z may differ slightly from the scout's (different granularity). Alternative
  (post-v1): ask Signals to emit structured anomaly detail in `extra` for pure projection.
- **D2 — Detection code split.** Keep `detection.py`'s *scoring* (`_evaluate_candidate`,
  `_compute_robust_z`) — the adapter uses it. Drop `selection.py`'s *discovery* from the v1 path
  (the scout owns "which insights are anomalous"). Both stay in-tree as the dormant
  `DeterministicSource` impl.
- **D3 — Sensitivity config becomes vestigial in v1.** `PulseSubscription`'s sensitivity presets /
  thresholds and the staff scan-config UI tune *detection* — which the scout now owns. v1 should
  hide/neutralize them (or repurpose to "which scout findings to surface"); do not delete the
  model yet. Open for review.
- **D4 — Proactive depth.** v1 = digest carries why + next-step + one-click insight (Max under the
  hood). Auto-running the next-step exploration in the background (no click at all) is post-v1.

## Non-goals (v1)

- No anomaly discovery/detection in Pulse (scout-only source).
- Do **not** rebuild the observability-gaps scout's "you're missing an insight" detection —
  surfacing/consuming its recommendations is a separate, later step (Pillar 2).
- No auto-fix / coding tasks — that is Signals' job.
- No changes to the scout's emit contract.
- No new REST surface on Signals (facade method only).

## Open questions (resolve in review / implementation research)

- **O1 — Read grain (DECIDED ✅): raw anomaly signals, not grouped reports.** A `SignalReport`
  groups signals across sources, so it is a fuzzy unit for "one metric anomaly." Pulse reads the
  **raw anomaly signal** (one anomaly → one finding, each with its `short_id` + `time_range`):
  `get_team_anomalies` queries ClickHouse `document_embeddings` (`product='signals'`, filtered to
  the anomaly-detection scout), not Postgres `SignalReport`s.
- **O2 — Scoping to the anomaly-detection scout.** All scouts emit `source_product='signals_scout'`,
  `source_type='cross_source_issue'`, so `source_product` alone is too broad. Scope via the scout
  `skill_name` (`signals-scout-anomaly-detection`, reachable through `SignalScoutRun` / the signal's
  `extra.scout_run_id`) or the `dedupe_keys` pattern (`metric_anomaly:` / `insight:`). Confirm the
  reliable key with the Signals team.
- **O3 — Sensitivity config fate (D3):** hide, repurpose to "which scout findings to surface," or
  keep `PulseSubscription`'s detection knobs? They tune detection, which the scout now owns.
- **O4 — Slicing:** this is plausibly two PRs — (a) `AnomalySource` interface + `ScoutAnomalySource`
  + facade read method + adapter (the source swap), and (b) proactive surfacing (full-context Max
  handoff + one-click insight). Confirm split before planning.

## Success criteria

- A team with the anomaly scout enrolled gets a Pulse digest whose findings are sourced entirely
  through `ScoutAnomalySource` (zero calls into `selection.py`/`detect_changes` in the v1 path).
- Each finding shows: the scout's anomaly, Pulse's re-scored numbers + chart, the causal narrative
  (flag/experiment/annotation/segment), and a working one-click "make this insight" + Max handoff
  carrying full finding context.
- Swapping in a stub second `AnomalySource` requires no change downstream of `Finding` (proves the
  boundary is real).
- A team without the scout enrolled gets a clear "enable the anomaly scout" empty state, not a
  broken/empty digest.

## Risks & mitigations

- **Coverage dependency (accepted):** Pulse v1 only works where the scout is enrolled
  (flag-gated, AI-data-processing-approved, has run on schedule). Mitigation: explicit empty state;
  the interface makes adding `DeterministicSource` for universal coverage a contained follow-up.
- **Numbers-in-prose / granularity (D1):** Pulse's re-scored numbers may differ from the scout's
  prose figures. Mitigation: Pulse presents its own consistent numbers; the scout's prose rides
  along as hypothesis context, not as the displayed figure.
- **New facade surface on Signals:** `get_team_anomalies` is new cross-product API. Mitigation:
  DTO-shaped (decoupled from row shape), facade-only, AI-approval gated, owned with the Signals team.
- **Empty/duplicate findings:** ensure the read method returns de-duplicated, anomaly-scoped
  signals for the period only (dedupe on `document_id`, per the ReplacingMergeTree pattern in
  `signal_queries.py`).

## Migration path

1. v1: `AnomalySource` interface + `ScoutAnomalySource` only (this doc).
2. Universal coverage: add `DeterministicSource` impl behind the same interface; prefer scout where
   enrolled, fall back to the built-in detector elsewhere.
3. Richer adapter: Signals emits structured anomaly detail → adapter becomes pure projection (drop
   re-scoring).
4. Pillar 2: consume observability-gaps recommendations to power "make this insight."
5. Deeper proactivity (D4): background-run the suggested next step via Max.
