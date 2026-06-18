# Dashboards Finder/grid experiment — criteria matrix

Source spec: [2026-06-17-dashboards-finder-grid-experiment-design.md](2026-06-17-dashboards-finder-grid-experiment-design.md)
Generated: 2026-06-17 (fresh-eyes test architect, proof-driven-dev Phase 2)

## Scale and triage (auto-applied while user away — confirm at human checkpoint)

31 requirements, 246 edge cases. The per-requirement density (~8) is appropriate for a complex feature,
but the total confirms this is **two bodies of work**: a frontend feature (REQ-01–15) and an experiment/measurement
layer (REQ-16–31). It is multi-PR. The matrix below is the full contract; the triage groups it into shippable increments.

Triage was applied by **rule** (not per-item by a human, who was away) — please confirm/adjust at the checkpoint:

- **must-have** edge cases (block verification): happy paths; control-path-untouched guarantees; safety fallbacks
  (flag undefined/unknown → control); data-integrity/rollback on move & duplicate; event-contract correctness +
  group/`$feature` association; and every load-bearing ambiguity called out in the Challenge section.
- **nice-to-have** edge cases (tracked, `OPTIONAL`, non-blocking this increment): exhaustive accessibility / viewport /
  RTL / unicode / injection / deep-nesting / redundant 4xx-5xx permutations. They remain in the matrix and should be
  covered before GA, just not gating the first increment.

### Suggested PR increments (build order)

1. **Foundation + Grid arm + core metric** — REQ-01, 02, 03, 04, 05, 07, 13(read+move), 16, 24. Ships behind the flag; control untouched; the `grid` arm fully usable; primary-metric event emitting.
2. **Finder arm** — REQ-06, 09, 10, 11 (folder-first nav, multi-select, rename, context menu).
3. **Clipboard + duplication** — REQ-08, 12 (cut=move, copy=duplicate, semantics).
4. **Measurement + analysis** — REQ-17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29, 30, 31 (events, guardrails, robust/CUPED metric, segmentation, decision rules, staged rollout). Several are analysis/config + queries, not UI code.
5. **Feedback affordance + icons** — REQ-14, 15 (small).

## Challenge items (spec under-specifies — must be pinned in the plan)

- CH-01: "has real folders" classifier (organization-state + cold-start segments) MUST exclude the auto-created `Unfiled/Dashboards` default — a project with only `Unfiled` is NOT organized. Load-bearing for all segmentation. (relates EC-27a, EC-26f)
- CH-02: cut is NOT a delete — a cut item must remain intact if the tab closes / navigation happens before paste-move resolves. (EC-08d)
- CH-03: copy=duplicate inheritance policy — sharing/public state and subscriptions must NOT be silently carried to the duplicate (no accidental public exposure / surprise re-sends). Define the exact policy. (EC-12c, EC-12d)
- CH-04: same-dashboard re-open is NOT a pogo-stick (only opening a _different_ dashboard counts as a failed first-open). (EC-21c)
- CH-05: multi-tab opens (A in one tab, B in another, same session) must not be miscounted as a pogo-stick. (EC-21i, EC-24a)
- CH-06: "New dashboard" created while drilled into a finder subfolder — define where it lands (current folder vs Unfiled). (EC-07d)
- CH-07: sidebar-vs-finder folder-create must not double-count `dashboard folder created`. (EC-18a)
- CH-08: CUPED handling for projects with no pre-exposure data (new projects) — drop vs impute; must not bias. (EC-23e)
- CH-09: platform validation (gating, before build) — group-level experiment + winsorized/median custom-property metric + CUPED must be confirmed supported. (EC-24e, EC-23h, EC-31d)

## Criteria matrix

```text
REQUIREMENTS:
  - id: REQ-01  priority: must-have
    description: Multivariate feature flag `dashboards-list-view` resolves to one of three arms (control | grid | finder)
    happy_path: An enrolled project receives a stable variant; the dashboards page renders the matching arm for every member of that project.
    proof_type: [test]
    edge_cases:
      - EC-01a [must] flag undefined/null (service unreachable) → fall back to control, never blank/crash [test]
      - EC-01b [must] unknown variant string → registry defaults to control, no throw [test]
      - EC-01c [must] empty-string variant → treated as control [test]
      - EC-01d [nice] loading/pending on first render → non-crashing placeholder, no flash that re-mounts mid-interaction [test, visual]
      - EC-01e [must] flag value differs across two tabs (cache refresh) → assignment stable per project, no mid-session split [test]
      - EC-01f [must] mapped component fails to mount (lazy-import error) → error boundary falls back to control [test]
      - EC-01g [must] flag returns boolean instead of string → coerce safely to control [test]
      - EC-01h [must] unauthenticated/expired session at load → flag path doesn't break the scene auth redirect [test]
      - EC-01i [nice] registry lookup case-sensitivity ("Finder" vs "finder") → only defined casing resolves [test]

  - id: REQ-02  priority: must-have
    description: Variant registry maps variant → component, mirroring authFlowVariants.ts
    happy_path: Registry exposes exactly control/grid/finder → DashboardsTable/Grid/Finder; DashboardsContent renders the mapped component.
    proof_type: [test]
    edge_cases:
      - EC-02a [must] missing key → control default, not undefined [test]
      - EC-02b [must] single source of arm defs — no duplicated switch elsewhere [test]
      - EC-02c [must] control (DashboardsTable) byte-for-byte unchanged vs baseline [test, visual]
      - EC-02d [must] default fallback is control specifically, never a treatment arm [test]

  - id: REQ-03  priority: must-have
    description: Control arm renders today's flat list unchanged
    happy_path: variant=control shows the existing flat table with no behavioral/visual change.
    proof_type: [test, visual]
    edge_cases:
      - EC-03a [nice] empty state identical to baseline [visual]
      - EC-03b [nice] single dashboard row [visual]
      - EC-03c [must] large list (500+) scrolls/paginates as before; no regression from the switch wrapper [test, visual]
      - EC-03d [must] existing "Move to folder" `…` menu still works in control [test]
      - EC-03e [nice] mobile/tablet identical to baseline [visual]

  - id: REQ-04  priority: must-have
    description: Grid arm renders cards grouped under collapsible folder headers
    happy_path: variant=grid renders cards grouped under collapsible folder section headers, all visible (no drill-in), reusing dashboardsLogic.
    proof_type: [test, visual]
    edge_cases:
      - EC-04a [must] zero folders (all Unfiled) → single Unfiled header, no dangling headers [visual]
      - EC-04b [nice] empty folder → header with zero-count affordance, not omitted [visual]
      - EC-04c [nice] exactly one dashboard in one folder [visual]
      - EC-04d [must] very large (50 folders / 1000 cards) → performant, no DOM blowup [test, visual]
      - EC-04e [nice] unicode/emoji/RTL folder name [visual]
      - EC-04f [nice] extremely long folder name truncates/wraps [visual]
      - EC-04g [must] collapse/expand persists per session, independent per folder [test, visual-flow]
      - EC-04h [must] nested folders render as headers in a stable order [test, visual]
      - EC-04i [nice] folder data loading → skeleton, not flash of "no dashboards" [visual]
      - EC-04j [nice] mobile/tablet reflow [visual]
      - EC-04k [must] stable sort with identical values [test]
      - EC-04l [nice] keyboard navigation of headers/cards [test, manual]

  - id: REQ-05  priority: must-have
    description: Grid drag-a-card-onto-a-folder-header to file a dashboard
    happy_path: Dragging a card onto a folder header moves the dashboard (via projectTreeDataLogic), reflected in the sidebar tree.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-05a [must] drop onto current folder (no-op) → no move event, no API call [test]
      - EC-05b [must] drop outside any header → cancels cleanly [test, visual-flow]
      - EC-05c [must] Escape/tab-close mid-drag → no partial move [test]
      - EC-05d [must] move 403 → revert, error surfaced, optimistic rollback [test]
      - EC-05e [must] move 404 (target folder deleted) → graceful, not orphaned [test]
      - EC-05f [must] move 409 (concurrent rename/move) → reconcile or roll back [test]
      - EC-05g [must] network timeout → rollback, retry, no silent loss [test]
      - EC-05h [must] concurrent move by another member → reconciles without throw [test]
      - EC-05i [must] rapid double-drag → debounced/queued, not double-move [test]
      - EC-05j [must] drop after unmount → no setState-on-unmounted / orphaned write [test]
      - EC-05k [nice] touch-drag on tablet → works or degrades to menu-move [manual, visual-flow]
      - EC-05l [must] keyboard users have a non-drag move path (menu) [test, manual]

  - id: REQ-06  priority: must-have
    description: Finder arm is folder-first by default — drill-in navigation + breadcrumb
    happy_path: variant=finder opens the top-level folder hierarchy; clicking a folder drills in; breadcrumb reflects the path.
    proof_type: [test, visual, visual-flow]
    edge_cases:
      - EC-06a [must] cold-start (all Unfiled) → opens to Unfiled node; extra nav step present (measured risk); find path still reaches dashboards [test, visual-flow]
      - EC-06b [must] drill into empty folder → empty view with back/breadcrumb, not a dead end [visual, visual-flow]
      - EC-06c [nice] deep nesting → breadcrumb truncates gracefully, drill in/out correct [test, visual]
      - EC-06d [must] breadcrumb click to an ancestor deleted by another user → fallback to nearest valid ancestor/root [test]
      - EC-06e [nice] browser back/forward maps to folder path or is explicitly excluded [test]
      - EC-06f [must] refresh while drilled in → restores to that folder (URL) or root deterministically [test]
      - EC-06g [nice] unicode/emoji/long name in breadcrumb [visual]
      - EC-06h [must] subtree load 500/503 → error+retry, not infinite spinner [test]
      - EC-06i [must] subtree unexpected shape (missing children) → render empty, no crash [test]
      - EC-06j [must] drill-in while loading → pending, no double-fetch [test]
      - EC-06k [nice] mobile/tablet folder-first nav usable [visual]
      - EC-06l [nice] keyboard/screen-reader navigable [test, manual]
      - EC-06m [must] multiple tabs drilled to different folders → independent per-tab nav state [test]

  - id: REQ-07  priority: must-have
    description: Held-constant chrome across arms (tabs, search, filters, New dashboard, data)
    happy_path: Tab bar, search, filters, "New dashboard" identical across arms; only the body differs.
    proof_type: [test, visual]
    edge_cases:
      - EC-07a [must] switch tab in grid/finder → body re-renders filtered set, chrome unchanged [test, visual-flow]
      - EC-07b [must] zero search results → same empty affordance as control [test, visual]
      - EC-07c [must] one result across folders → consistent, open_source=search [test]
      - EC-07d [must] New dashboard created while drilled into a finder subfolder → lands per defined rule (CH-06) [test]
      - EC-07e [must] filter + grouping in grid → empty/hidden folders consistent [test, visual]
      - EC-07f [nice] Templates tab inside a folder-first arm → defined fallback (templates not folderable) [test, visual]
      - EC-07g [must] search HTML/script injection → rendered safe, no XSS [test]
      - EC-07h [nice] unicode/emoji search query [test]

  - id: REQ-08  priority: must-have
    description: Finder clipboard state machine (cut+paste=move, copy+paste=duplicate)
    happy_path: cut marks for move, copy marks for duplicate; paste performs move (/move/) or duplicate (duplicateDashboard) then clears the buffer.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-08a [must] paste with empty buffer → disabled/no-op, no API call [test]
      - EC-08b [must] cut then paste into own folder → no-op move, buffer clears [test]
      - EC-08c [must] copy then paste into same folder → disambiguated name, no overwrite [test]
      - EC-08d [must] cut then navigate/close before paste → cut item NOT deleted (CH-02) [test]
      - EC-08e [must] cut item deleted by another user before paste → 404 handled, buffer clears with error [test]
      - EC-08f [must] paste-move target folder deleted concurrently → error, item stays [test]
      - EC-08g [must] duplicate returns 500 mid-op → no half-created dashboard [test]
      - EC-08h [must] rapid double-paste → only one move/duplicate [test]
      - EC-08i [must] cut after copy (buffer overwrite) → only latest intent [test]
      - EC-08j [must] paste-move 403 → rolled back, item stays [test]
      - EC-08k [must] paste offline/timeout → buffer preserved, retry, no loss [test]
      - EC-08l [nice] quota exceeded on duplicate → 422 surfaced, buffer state defined [test]
      - EC-08m [must] paste after navigation → no setState-on-unmounted; lands or aborts cleanly [test]

  - id: REQ-09  priority: must-have
    description: Multi-select + bulk move via clipboard/drag
    happy_path: shift-range multi-select; one cut/copy+paste (or drag) applies to all; multi_select_count reflects the count.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-09a [must] select one (degenerate) → count=1, single behavior [test]
      - EC-09b [must] select all in large folder (1000) → performant, no lock-up [test]
      - EC-09c [must] partial success (some 404/403) → succeeded moved, failed reported [test]
      - EC-09d [must] selection includes a folder + its own contents (move into itself) → rejected, no cycle [test]
      - EC-09e [must] shift-range across collapsed/expanded → defined semantics, no off-by-one [test]
      - EC-09f [must] one selected item deleted before bulk paste → skipped, rest proceed [test]
      - EC-09g [must] empty selection then cut/copy → no-op [test]
      - EC-09h [nice] keyboard shift+arrow range selection [test, manual]

  - id: REQ-10  priority: must-have
    description: Rename-in-place (folders/dashboards) in finder
    happy_path: rename turns label editable; commit via projectTreeDataLogic; sidebar stays consistent.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-10a [must] empty/whitespace name → field error, original retained [test]
      - EC-10b [must] name collision in folder → rejected/disambiguated, no silent overwrite [test]
      - EC-10c [nice] unicode/emoji/RTL accepted and rendered [test, visual]
      - EC-10d [must] HTML/script injection in name → escaped, no XSS [test]
      - EC-10e [nice] extremely long name → rejected at boundary or truncated [test]
      - EC-10f [must] API 403/409 → reverts, error, optimistic rollback [test]
      - EC-10g [must] Escape cancels → original restored, no API call [test]
      - EC-10h [must] concurrent rename → last-write reconciles, no flicker loop [test]
      - EC-10i [must] blur vs Enter → defined commit-vs-cancel [test]
      - EC-10j [must] rename unchanged → no-op, no spurious event [test]
      - EC-10k [nice] keyboard-only rename (F2/Enter/Esc) [test, manual]

  - id: REQ-11  priority: must-have
    description: Right-click context menu in finder
    happy_path: right-click opens a menu (cut/copy/paste, move-to-folder, rename, delete); selecting invokes the flow.
    proof_type: [test, visual]
    edge_cases:
      - EC-11a [must] right-click empty canvas → only context-appropriate actions (New folder/Paste) [test, visual]
      - EC-11b [must] paste buffer empty → Paste disabled, not inconsistently hidden [test]
      - EC-11c [nice] near viewport edge → repositions on-screen [visual]
      - EC-11d [must] during loading → data-dependent actions disabled [test]
      - EC-11e [must] item deleted by another user → action 404s gracefully [test]
      - EC-11f [must] delete folder containing dashboards → confirm + defined cascade [test]
      - EC-11g [nice] keyboard access (Shift+F10/Menu) + arrows [test, manual]
      - EC-11h [must] right-click on multi-selection → applies to whole selection [test]
      - EC-11i [must] permission-denied user → destructive actions hidden/disabled [test]

  - id: REQ-12  priority: must-have
    description: copy=duplicate preserves correct dashboard semantics (tiles, sharing, subscriptions)
    happy_path: copy+paste creates a real dashboard via duplicateDashboard in the target folder, tiles duplicated, sharing/subscriptions per policy (CH-03).
    proof_type: [test]
    edge_cases:
      - EC-12a [must] duplicate zero-tile dashboard → clean empty duplicate [test]
      - EC-12b [nice] duplicate many tiles (max) → all copied, no truncation [test]
      - EC-12c [must] duplicate shared/public → sharing NOT silently inherited (CH-03) [test]
      - EC-12d [must] duplicate with active subscriptions → NOT silently copied (CH-03) [test]
      - EC-12e [must] duplicate then delete source → duplicate independent (deep copy) [test]
      - EC-12f [nice] tiles referencing soft-deleted insights → graceful, no crash [test]
      - EC-12g [must] name collision in target → disambiguated [test]
      - EC-12h [must] team/project isolation → duplicate stays in same team [test]

  - id: REQ-13  priority: must-have
    description: Writes delegate to projectTreeDataLogic; sidebar stays consistent (single source of truth)
    happy_path: every mutation calls existing projectTreeDataLogic actions; sidebar reflects changes; FileSystem rows are the single source of truth.
    proof_type: [test]
    edge_cases:
      - EC-13a [must] finder move updates sidebar without manual refresh [test]
      - EC-13b [must] folder created in sidebar appears in finder/grid and vice versa [test]
      - EC-13c [must] rollback on server error reverts BOTH body and sidebar [test]
      - EC-13d [nice] undo of a finder move restores both views [test]
      - EC-13e [must] concurrent writes from body + sidebar → no duplicate calls, consistent [test]
      - EC-13f [must] delete folder from sidebar while finder drilled into it → finder navigates up, no stale pane [test]
      - EC-13g [must] projectTreeDataLogic not mounted when a write fires → reaches logic (lazy) or queues, no dropped mutation [test]

  - id: REQ-14  priority: nice-to-have
    description: "Not a fan? tell us" feedback affordance in non-control arms only
    happy_path: grid/finder show a lightweight feedback control; control does not; captures qualitative feedback, no exposure-leaking toggle.
    proof_type: [test, visual]
    edge_cases:
      - EC-14a [must] control does NOT render the affordance [test, visual]
      - EC-14b [must] offers NO variant/view switch (no exposure leak) [test]
      - EC-14c [nice] empty text submit handled per policy [test]
      - EC-14d [nice] long/unicode/HTML text stored safely, no XSS, bounded [test]
      - EC-14e [must] double-click → one event, button disabled in-flight [test]
      - EC-14f [must] network error → re-enables, retry, no silent loss [test]
      - EC-14g [nice] keyboard-accessible + screen-reader labelled [test, manual]
      - EC-14h [nice] copy reads low-pressure + Sentence casing [manual]

  - id: REQ-15  priority: nice-to-have
    description: Generic dashboard type-icon in grid/finder (v1, no thumbnails)
    happy_path: cards/rows show a generic dashboard glyph; consistent across all dashboards.
    proof_type: [visual, manual]
    edge_cases:
      - EC-15a [must] folder vs dashboard icons distinguishable [visual]
      - EC-15b [nice] renders at all sizes/viewports [visual]
      - EC-15c [must] icon present even when metadata partially missing, never broken-image [test, visual]
      - EC-15d [nice] "too samey" manual judgment flag [manual]

  - id: REQ-16  priority: must-have
    description: Event `dashboard opened from list` {ms_since_list_loaded, used_search, clicks_before_open, open_source}
    happy_path: opening a dashboard from the list fires exactly one event with those props; open_source in {root, folder, grouped, search}.
    proof_type: [test]
    edge_cases:
      - EC-16a [must] open without search → used_search=false, open_source != search [test]
      - EC-16b [must] open via search → open_source=search, used_search=true [test]
      - EC-16c [must] idle-tab ms → raw or capped per defined contract (idle cap is in the metric) [test]
      - EC-16d [must] same dashboard opened twice → two events (or defined dedupe), ms from list load each time [test]
      - EC-16e [must] open_source enums exactly the documented set per arm [test]
      - EC-16f [must] clicks_before_open at 0 and large → accurate [test]
      - EC-16g [must] keyboard open (Enter) → event fires with correct props [test]
      - EC-16h [must] list never finished loading → ms from a defined anchor, not NaN/negative [test]
      - EC-16i [must] event carries $feature/dashboards-list-view + project group [test]
      - EC-16j [must] navigation away before flush → event still captured (fired pre-nav) [test]
      - EC-16k [must] clock skew/negative elapsed → clamped >= 0 [test]

  - id: REQ-17  priority: must-have
    description: Event `dashboard moved to folder` {method (drag|menu|clipboard), multi_select_count}
    happy_path: a successful move fires once with method + multi_select_count.
    proof_type: [test]
    edge_cases:
      - EC-17a [must] single-item → count=1 [test]
      - EC-17b [must] bulk N → defined contract (one event count=N, or N events), consistent [test]
      - EC-17c [must] method enum exactly drag|menu|clipboard [test]
      - EC-17d [must] failed/rolled-back move does NOT fire (no false positives) [test]
      - EC-17e [must] no-op move does NOT fire [test]
      - EC-17f [must] partial bulk → count = items actually moved [test]
      - EC-17g [must] carries project group + $feature [test]

  - id: REQ-18  priority: must-have
    description: Folder lifecycle events `dashboard folder created|renamed|deleted`
    happy_path: create/rename/delete a folder from grid/finder fires the corresponding single event.
    proof_type: [test]
    edge_cases:
      - EC-18a [must] finder vs sidebar create → no double-count (CH-07) [test]
      - EC-18b [must] no-op rename does NOT fire renamed [test]
      - EC-18c [must] failed delete (403/409) does NOT fire deleted [test]
      - EC-18d [must] delete folder w/ dashboards → single delete event (not per child) per contract [test]
      - EC-18e [nice] rapid create-then-delete → both fire in order [test]
      - EC-18f [must] all three carry project group + $feature [test]

  - id: REQ-19  priority: must-have
    description: Event `dashboards clipboard action` {action (cut|copy|paste), result (move|duplicate), item_count}
    happy_path: each clipboard op fires; cut/copy carry action+item_count; paste carries result=move|duplicate.
    proof_type: [test]
    edge_cases:
      - EC-19a [must] action enum cut|copy|paste; result only on paste [test]
      - EC-19b [must] item_count matches selection (1 and N) [test]
      - EC-19c [must] failed paste → defined (failure marker or none), no phantom success [test]
      - EC-19d [nice] cut then cut (overwrite) → two cut events, latest count [test]
      - EC-19e [must] paste resolving to no-op move → consistent with REQ-17 no-op rule [test]
      - EC-19f [must] carries project group + $feature [test]
      - EC-19g [must] empty-buffer paste fires NO event [test]

  - id: REQ-20  priority: nice-to-have
    description: Event `dashboards view feedback` from the "not a fan?" affordance
    happy_path: submitting feedback fires one event carrying arm/variant context.
    proof_type: [test]
    edge_cases:
      - EC-20a [must] fires only in non-control arms [test]
      - EC-20b [must] double-submit → exactly one event [test]
      - EC-20c [must] carries $feature + project group [test]
      - EC-20d [nice] unicode/HTML text carried/escaped safely [test]
      - EC-20e [nice] network failure → retry, not double-counted [test]

  - id: REQ-21  priority: must-have
    description: First-open-success / anti-pogo-stick guardrail from existing pageview sequences (backtestable)
    happy_path: a find "succeeds" iff the first dashboard opened in a session is the one kept (no bounce-to-list + open of a DIFFERENT dashboard in-window); pogo-stick rate must not rise C/B vs A.
    proof_type: [test]
    edge_cases:
      - EC-21a [must] open A, stay → success [test]
      - EC-21b [must] open A, bounce, open B in-window → pogo-stick (failure) [test]
      - EC-21c [must] open A, return, re-open SAME A → NOT a pogo-stick (CH-04) [test]
      - EC-21d [must] open B after window closes → new session, not pogo-stick [test]
      - EC-21e [must] zero-open session → excluded from first-open denominator (it's REQ-22) [test]
      - EC-21f [must] backtest reproduces a baseline rate on today's pageviews [test]
      - EC-21g [nice] interleaved non-dashboard pages → tolerant, no miscount [test]
      - EC-21h [must] out-of-order/duplicate pageviews → idempotent, no double-count [test]
      - EC-21i [must] open A in one tab, B in another → not mis-read as pogo-stick (CH-05) [test]

  - id: REQ-22  priority: must-have
    description: Find-conversion (non-bounce) guardrail; first-class for cold-start
    happy_path: share of list visits that open >= 1 dashboard in-session, per arm/project; must not drop C/B vs A, esp. cold-start.
    proof_type: [test]
    edge_cases:
      - EC-22a [must] visit opens >=1 → converted [test]
      - EC-22b [must] visit opens zero → non-converted [test]
      - EC-22c [must] cold-start segment isolated correctly (CH-01) [test]
      - EC-22d [must] open via "New dashboard" (created not found) → defined whether it counts (likely not) [test]
      - EC-22e [must] session-window matches primary + pogo-stick definitions (consistent boundary) [test]
      - EC-22f [must] mid-session list reload → defined visit counting, no double-count [test]

  - id: REQ-23  priority: must-have
    description: SECONDARY value-check (not a gate) — robust time-to-open: per-project median (winsorized, idle-capped, CUPED)
    happy_path: time-to-open aggregated per-project as a winsorized/idle-capped median (CUPED optional), equal-weighting projects; read directionally to confirm an adoption lift translates into faster finding — never a ship gate.
    proof_type: [test]
    edge_cases:
      - EC-23a [must] idle-tab outlier capped before aggregation [test]
      - EC-23b [must] project with one open → median defined, not NaN [test]
      - EC-23c [must] project with zero opens → excluded, not counted as zero [test]
      - EC-23d [nice] winsor boundary inclusive/exclusive defined [test]
      - EC-23e [must] CUPED with no pre-exposure data → defined handling, no bias (CH-08) [test]
      - EC-23f [must] negative/zero ms reaching aggregation → clamped/filtered [test]
      - EC-23g [nice] even vs odd count median interpolation defined [test]
      - EC-23h [must] dogfood metric validation gate before clock starts (CH-09) [test, manual]
      - EC-23i [must] equal-weight projects (no single project dominates) [test]
      - EC-23j [nice] identical values → median stable [test]

  - id: REQ-24  priority: must-have
    description: Exposure & group association — events carry $feature + project group; exposure via $feature_flag_called
    happy_path: frontend sets the `project` group on events; events carry $feature/dashboards-list-view; $feature_flag_called records exposure for group-level aggregation.
    proof_type: [test]
    edge_cases:
      - EC-24a [must] project group set on EVERY new event (none dropped from aggregation) (CH-05) [test]
      - EC-24b [must] $feature_flag_called fires once per exposure, not per render storm [test]
      - EC-24c [must] event captured before flag resolves → group/$feature attached or deferred [test]
      - EC-24d [nice] missing project group on client → captured but flagged ungrouped, no crash [test]
      - EC-24e [must] platform validation: group-level + winsorized/median metric + CUPED supported (CH-09) [test, manual]
      - EC-24f [must] two members → same group key, no fragmentation [test]
      - EC-24g [must] $feature value matches the rendered arm (no skew) [test]

  - id: REQ-25  priority: must-have
    description: Group-level randomization on `project` (no within-project spillover)
    happy_path: assignment at project-group level so every member sees the same arm; shared folders never leak another arm's behavior.
    proof_type: [test]
    edge_cases:
      - EC-25a [must] two members of same project → identical variant [test]
      - EC-25b [must] user in multiple projects in different arms → per-project assignment, no cross-leak [test]
      - EC-25c [must] project with no group id → defined fallback (control), no random per-person split [test]
      - EC-25d [nice] new member mid-experiment → inherits project's arm [test]
      - EC-25e [must] folder filed by finder member visible to all, but each renders their (same) arm [test]

  - id: REQ-26  priority: must-have
    description: Pre-exposure dashboard-count segmentation (1-5 / 6-20 / 21+), pinned pre-exposure
    happy_path: each project bucketed by pre-exposure dashboard count; analysis uses fixed pre-exposure buckets, never post-treatment count.
    proof_type: [test]
    edge_cases:
      - EC-26a [must] boundary (exactly 5/6/20/21) → correct bucket, inclusive/exclusive defined [test]
      - EC-26b [must] zero dashboards at exposure → defined bucket, not unbucketed [test]
      - EC-26c [must] copy=duplicate raises live count → segmentation still uses pinned pre-exposure count [test]
      - EC-26d [nice] deletions during run → segmentation unchanged (pinned) [test]
      - EC-26e [must] missing exposure timestamp → defined pinning anchor (enrollment time) [test]
      - EC-26f [must] cold-start defined independently of count (21+ can be cold-start) (CH-01) [test]

  - id: REQ-27  priority: must-have
    description: Pre-registered segments only — organization-state + cold-start, no post-hoc fishing
    happy_path: analysis restricted to the three pre-registered segment families; no segment introduced post-launch.
    proof_type: [test, manual]
    edge_cases:
      - EC-27a [must] "has real folders" excludes auto-created Unfiled/Dashboards (CH-01) [test]
      - EC-27b [must] cold-start vs org-state mutually consistent (exactly one class) [test]
      - EC-27c [must] segment defs frozen/pre-registered before launch (governance artifact) [manual]
      - EC-27d [nice] folder-state change mid-run → segmented by pre-exposure org-state (pinned) [test]

  - id: REQ-28  priority: must-have
    description: PRIMARY metric — folder-organization adoption: share of exposed projects that create a real (non-Unfiled) folder or move a dashboard into one within the window
    happy_path: project-level adoption proportion at a low single-digit baseline, per arm; ship/no-ship gated on this PLUS the guardrails; derived from the new move/folder events; expected C ≤ B. Organizing depth (moves/creations per organizing project) is the supporting secondary.
    proof_type: [test]
    edge_cases:
      - EC-28a [must] zero-organizing user counted in denominator [test]
      - EC-28b [must] control baseline = existing menu-move only (apples-to-apples) [test]
      - EC-28c [must] failed/rolled-back moves not counted (consistent w/ REQ-17) [test]
      - EC-28d [nice] drag-undo-drag churn → net actions per rule, not inflated [test]

  - id: REQ-29  priority: nice-to-have
    description: Secondary north-star — dashboard engagement (opens/user/week, return visits) from existing events
    happy_path: opens per active user/week + return visits from existing events, by arm.
    proof_type: [test]
    edge_cases:
      - EC-29a [must] active-user denominator consistent across arms [test]
      - EC-29b [must] reuses existing events, no schema change [test]
      - EC-29c [nice] week boundary / partial weeks (tz vs UTC) defined [test]
      - EC-29d [nice] duplicate dashboards inflating opens → no double-count of a single view [test]

  - id: REQ-30  priority: must-have
    description: Ship/no-ship decision rules — adoption primary + guardrail vetoes + cold-start contingency
    happy_path: ship on an adoption lift over A with NO guardrail regression (first-open success, find-conversion, engagement); A-vs-B, A-vs-C, and C-vs-B are all real reads; cold-start contingency (ship C / gate B) honored.
    proof_type: [test, manual]
    edge_cases:
      - EC-30a [must] B beats A but pogo-stick regresses → NO-SHIP B (guardrail veto) [test]
      - EC-30b [must] B beats A but cold-start find-conversion drops → contingency (ship C / gate B) [test]
      - EC-30c [must] C-vs-B is a real read but not the sole ship gate (adoption lift + guardrails gate) [test, manual]
      - EC-30d [nice] adoption result below the pre-registered MDE → require the powered threshold before ship [manual]
      - EC-30e [must] both null → keep A, bank learning, no fishing [test, manual]
      - EC-30f [must] guardrail regression with no primary win → no-ship [test]

  - id: REQ-31  priority: must-have
    description: Staged rollout — dogfood before the experiment clock starts
    happy_path: flag first enabled for PostHog org (+ friendly accounts) to validate UX + the new metric; only then the all-projects experiment starts.
    proof_type: [test, manual]
    edge_cases:
      - EC-31a [must] dogfood exposure excluded from the experiment analysis window [test]
      - EC-31b [must] dogfood (org) → experiment (group-level all) transition clean, no double-exposure [test]
      - EC-31c [nice] friendly-account list finite/explicit, no accidental broad enable [manual]
      - EC-31d [must] metric-validation go/no-go gate blocks start if primary is insane (CH-09) [manual]

SUMMARY:
  total_requirements: 31
  total_edge_cases: 246
  proof_types (overlapping buckets): test ~168, visual 36, visual_flow 10, manual 32
  priority (rule-applied, confirm at checkpoint): must-have core ~ REQ-01..13,16,17,18,19,21,22,23,24,25,26,27,28,30,31; nice-to-have REQ-14,15,20,29 + flagged [nice] edge cases
```
