# Dashboards control/explorer experiment — criteria matrix

Source spec: [2026-06-17-dashboards-finder-grid-experiment-design.md](2026-06-17-dashboards-finder-grid-experiment-design.md)
Generated: 2026-06-17 (fresh-eyes test architect, proof-driven-dev Phase 2); updated for the two-arm control/explorer cut.

> **Scope note:** the experiment is now a **two-arm A/B** — `control` (A) vs `explorer` (B). `explorer` is the arm formerly called "finder" (drill-in). Two cuts got here: the flat-card **grid arm was retired** (original finder/grid reframe), then the **tree arm was built but cut before launch** (the team's ship intent was to run explorer regardless of how tree performed, so a three-arm test risked an ambiguous tie). REQ-04/REQ-05 (the grid arm) **and** REQ-32 (the tree panel) are **retired** — kept as explicit retirement stubs, not deleted. The explorer's affordances (search, compacted chains, breadcrumb sibling dropdowns, "Move to…" picker, "New folder") and the shared folder-rows data layer (empty folders, `folderTree`, `folderSiblings`) all survive — the explorer still ships them. Items genuinely not built on the current branch are marked **DEFERRED**.

## Scale and triage (auto-applied while user away — confirm at human checkpoint)

The matrix below is the full contract; the triage groups it into shippable increments. After the primary-metric pivot to **folder-organization adoption**, the load-bearing instrumentation is the arm-agnostic `dashboard moved to folder` event (REQ-17, fired on the shared `projectTreeDataLogic` move path) — so REQ-16 (`opened from list`) moved to the measurement increment and is **DEFERRED**. This remains **two bodies of work**: a frontend feature and an experiment/measurement layer. It is multi-PR.

Triage was applied by **rule** (not per-item by a human, who was away) — please confirm/adjust at the checkpoint:

- **must-have** edge cases (block verification): happy paths; control-path-untouched guarantees; safety fallbacks
  (flag undefined/unknown → control); data-integrity/rollback on move & duplicate; event-contract correctness +
  group/`$feature` association; and every load-bearing ambiguity called out in the Challenge section.
- **nice-to-have** edge cases (tracked, `OPTIONAL`, non-blocking this increment): exhaustive accessibility / viewport /
  RTL / unicode / injection / deep-nesting / redundant 4xx-5xx permutations. They remain in the matrix and should be
  covered before GA, just not gating the first increment.

### Suggested PR increments (build order)

The current branch bundles the foundation, the **explorer** treatment arm, the shared folder-data layer, the explorer's organizing toolkit (drag, per-card menu, "Move to…", clipboard, rename, "New folder"), and the load-bearing primary-metric event — all behind the flag, control untouched. The tree arm was built then cut (REQ-32 retired).

1. **Foundation + explorer arm + core metric** (on this branch) — REQ-01, 02, 03, 06, 07, 08, 10, 11, 12, 13, 15, 17, 33, 34, 35, 36, 37. Variant switch; control byte-for-byte unchanged; explorer usable; folder rows loaded (empty folders appear); `dashboard moved to folder` emitting on the shared move path.
2. **Measurement + analysis** — REQ-16 (DEFERRED `opened from list`), 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29, 30, 31, 24 (events, guardrails, robust/CUPED metric, segmentation, decision rules, staged rollout, exposure/group). Several are analysis/config + queries, not UI code.
3. **Power features deferred from increment 1** — REQ-09 (multi-select / bulk), the move-event prop contract (`method` / `multi_select_count`), the feedback affordance + analytics events (REQ-14, 18, 19, 20), and copy=paste placement in the target folder.

> **Retired:** REQ-04 (grid cards under folder headers) and REQ-05 (grid drag-to-header) are retired with the grid arm. REQ-32 (the LemonTree panel) is retired with the tree arm. Their useful drag/no-op/rollback edge cases are folded into the explorer drag requirement (REQ-33).

## Challenge items (spec under-specifies — must be pinned in the plan)

- CH-01: "has real folders" classifier (organization-state + cold-start segments) MUST exclude the auto-created `Unfiled/Dashboards` default — a project with only `Unfiled` is NOT organized. Load-bearing for all segmentation. (relates EC-27a, EC-26f)
- CH-02: cut is NOT a delete — a cut item must remain intact if the tab closes / navigation happens before paste-move resolves. (EC-08d)
- CH-03: copy=duplicate inheritance policy — sharing/public state and subscriptions must NOT be silently carried to the duplicate (no accidental public exposure / surprise re-sends). Define the exact policy. (EC-12c, EC-12d)
- CH-04: same-dashboard re-open is NOT a pogo-stick (only opening a _different_ dashboard counts as a failed first-open). (EC-21c)
- CH-05: multi-tab opens (A in one tab, B in another, same session) must not be miscounted as a pogo-stick. (EC-21i, EC-24a)
- CH-06: "New dashboard" created while drilled into an explorer subfolder — define where it lands (current folder vs Unfiled). (EC-07d)
- CH-07: sidebar-vs-explorer folder-create must not double-count `dashboard folder created` (a measurement-increment event). (EC-18a)
- CH-08: CUPED handling for projects with no pre-exposure data (new projects) — drop vs impute; must not bias. (EC-23e)
- CH-09: platform validation (gating, before build) — group-level experiment + winsorized/median custom-property metric + CUPED must be confirmed supported. (EC-24e, EC-23h, EC-31d)

## Criteria matrix

```text
REQUIREMENTS:
  - id: REQ-01  priority: must-have
    description: Multivariate feature flag `dashboards-list-view` resolves to one of two live arms (control | explorer); retired strings (grid | finder | tree) resolve to control
    happy_path: An enrolled project receives a stable variant; the dashboards page renders the matching arm for every member of that project; any retired variant string resolves to control.
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
      - EC-01i [nice] registry lookup case-sensitivity ("Explorer" vs "explorer") → only defined casing resolves [test]

  - id: REQ-02  priority: must-have
    description: Variant registry maps variant → component, mirroring authFlowVariants.ts
    happy_path: resolveDashboardsListViewVariant + DASHBOARDS_LIST_VIEW_VARIANTS expose exactly control/explorer; DashboardsContent renders DashboardsTableContainer / DashboardsExplorer accordingly.
    proof_type: [test]
    edge_cases:
      - EC-02a [must] missing key → control default, not undefined [test]
      - EC-02b [must] single source of arm defs — no duplicated switch elsewhere [test]
      - EC-02c [must] control (DashboardsTableContainer) byte-for-byte unchanged vs baseline [test, visual]
      - EC-02d [must] default fallback is control specifically, never a treatment arm [test]
      - EC-02e [must] retired strings ("grid", "finder", "tree") resolve to control, not a treatment arm [test]

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

  - id: REQ-04  priority: RETIRED
    description: "[RETIRED with the grid arm] Grid arm renders cards grouped under collapsible folder headers"
    happy_path: N/A — the flat-card grid arm was dropped in the original finder/grid reframe. Folder-grouping now lives in the explorer (subfolder cards) — see REQ-06. Empty-folder and stable-order coverage moved to REQ-37 (folder-rows data layer).
    proof_type: []
    edge_cases: []

  - id: REQ-05  priority: RETIRED
    description: "[RETIRED with the grid arm] Grid drag-a-card-onto-a-folder-header to file a dashboard"
    happy_path: N/A — drag-to-folder survives in the explorer arm but onto folder *cards*, not collapsible headers. The drag/no-op/rollback/keyboard-fallback edge cases moved to REQ-33.
    proof_type: []
    edge_cases: []

  - id: REQ-06  priority: must-have
    description: Explorer arm is folder-first by default — drill-in navigation + breadcrumb (with sibling-folder dropdowns) + compacted single-child chains
    happy_path: variant=explorer opens the top-level folder hierarchy as folder + dashboard cards; clicking a folder card drills in; the breadcrumb reflects the path, each crumb navigates, and crumbs with siblings carry a jump-to-sibling dropdown; single-child folder chains compact to one card (one click to a buried dashboard).
    proof_type: [test, visual, visual-flow]
    edge_cases:
      - EC-06a [must] cold-start (all Unfiled) → opens to the Unfiled subtree; extra nav step present (measured risk); find path still reaches dashboards [test, visual-flow]
      - EC-06b [must] drill into empty folder → "This folder is empty" view, breadcrumb still navigates back, not a dead end [visual, visual-flow]
      - EC-06c [must] single-child folder chain → compacts to one card labeled "A / B / C", clicking navigates to the chain end (compactFolderChain) [test, visual]
      - EC-06d [must] breadcrumb click to an ancestor deleted by another user → fallback to nearest valid ancestor/root [test]
      - EC-06e [must] crumb with >1 sibling → sibling dropdown lists the siblings, selecting one navigates; crumb with no siblings shows no dropdown (folderSiblings) [test, visual]
      - EC-06f [must] navigate state is per-tab (currentFolder is a reducer, not URL) → multiple tabs drilled to different folders stay independent [test]
      - EC-06g [nice] unicode/emoji/long name in breadcrumb + sibling dropdown [visual]
      - EC-06h [must] folder rows load 500/503 → toast error + retry path, not infinite spinner; structure degrades to Unfiled, not a crash [test]
      - EC-06i [must] folder/dashboard rows unexpected shape (missing path/ref) → render under Unfiled, no crash [test]
      - EC-06j [must] drill-in while loading → spinner only while empty + loading + not searching; no double-fetch [test]
      - EC-06k [nice] mobile/tablet folder-first nav usable [visual]
      - EC-06l [nice] keyboard/screen-reader navigable (breadcrumb buttons, folder cards) [test, manual]

  - id: REQ-07  priority: must-have
    description: Held-constant chrome across arms (tabs, search, filters, New dashboard, data)
    happy_path: Tab bar, search, filters, "New dashboard" identical across arms; only the body differs.
    proof_type: [test, visual]
    edge_cases:
      - EC-07a [must] switch tab in explorer → body re-renders filtered set, chrome unchanged [test, visual-flow]
      - EC-07b [must] zero search results → explorer shows "No dashboards match your search"; control shows its empty affordance [test, visual]
      - EC-07c [must] explorer search flips to a flat results grid (DashboardsFiltersBar drives dashboardsLogic.filters.search) [test]
      - EC-07d [must] New dashboard created while drilled into an explorer subfolder → lands per defined rule (CH-06) — DEFERRED until CH-06 pinned [test]
      - EC-07e [n/a] RETIRED with the tree arm — filter-applied-in-tree recursive-subtree case [n/a]
      - EC-07f [nice] Templates tab inside the explorer arm → defined fallback (templates not folderable) [test, visual]
      - EC-07g [must] search HTML/script injection → rendered safe, no XSS [test]
      - EC-07h [nice] unicode/emoji search query [test]

  - id: REQ-08  priority: must-have
    description: Explorer clipboard state machine (cut+paste=move, copy+paste=duplicate)
    happy_path: cut marks for move, copy marks for duplicate; the "Paste into this folder" button shows only when the buffer is non-empty; paste performs move (moveDashboardToFolder → moveItem) or duplicate (duplicateDashboard) then clears the buffer.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-08a [must] empty buffer → no "Paste" affordance rendered; pasteIntoFolder with null buffer is a no-op [test]
      - EC-08b [must] cut then paste into own folder → no-op move (calculateMovePath isValidMove=false), buffer clears [test]
      - EC-08c [must] copy=paste lands the duplicate in its default (Unfiled) folder, not the paste-target — placement DEFERRED (CH-03 inheritance still honored) [test]
      - EC-08d [must] cut then navigate/close before paste → cut item NOT deleted (CH-02 — clipboard is intent only) [test]
      - EC-08e [must] cut item deleted by another user before paste → 404 handled, buffer clears with error [test]
      - EC-08f [must] paste-move target folder deleted concurrently → error, item stays [test]
      - EC-08g [must] duplicate returns 500 mid-op → no half-created dashboard [test]
      - EC-08h [must] rapid double-paste → only one move/duplicate [test]
      - EC-08i [must] cut after copy (buffer overwrite) → only latest intent [test]
      - EC-08j [must] paste-move 403 → rolled back, item stays [test]
      - EC-08k [must] paste offline/timeout → buffer preserved, retry, no loss [test]
      - EC-08l [nice] quota exceeded on duplicate → 422 surfaced, buffer state defined [test]
      - EC-08m [must] paste after navigation → no setState-on-unmounted; lands or aborts cleanly [test]

  - id: REQ-09  priority: DEFERRED
    description: "[DEFERRED — not built] Multi-select + bulk move via clipboard/drag"
    happy_path: shift-range multi-select; one cut/copy+paste (or drag) applies to all; multi_select_count reflects the count. Not built on the current branch — organizing is one item at a time; `multi_select_count` is part of the deferred move-event prop contract. Edge cases retained for the future increment.
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
    description: Inline rename-in-place (dashboards) in the explorer
    happy_path: Rename (from the per-card menu) turns the card label into an autofocused input; onBlur is the single commit path (renameDashboard → dashboardsModel.updateDashboard with undo); Enter blurs to commit, Escape resets the value then stopRenaming so the unmount-blur is a no-op.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-10a [must] empty/whitespace name → trimmed to empty → no-op (renameDashboard guards trimmed && trimmed !== current) [test]
      - EC-10b [must] name collision → updateDashboard handles per existing dashboard-rename behavior, no silent data loss [test]
      - EC-10c [nice] unicode/emoji/RTL accepted and rendered [test, visual]
      - EC-10d [must] HTML/script injection in name → escaped, no XSS [test]
      - EC-10e [nice] extremely long name → handled per existing updateDashboard boundary [test]
      - EC-10f [must] updateDashboard error → existing model error handling (undo support) [test]
      - EC-10g [must] Escape cancels → original value restored, stopRenaming, no updateDashboard call [test]
      - EC-10h [must] Enter then unmount → single commit (Enter blurs once; reducer clears renamingDashboardId on renameDashboard) [test]
      - EC-10i [must] rename unchanged → no-op, no updateDashboard call [test]
      - EC-10j [nice] folder rename → DEFERRED (only dashboard inline-rename is built; folder rename via sidebar) [test]
      - EC-10k [nice] keyboard-only rename (Enter/Esc) [test, manual]

  - id: REQ-11  priority: must-have
    description: Per-card actions menu in the explorer cards (Open / Rename / Move to… / Cut / Copy / Delete)
    happy_path: A DropdownMenu on each dashboard card exposes Open (router push), Rename (startRenaming), Move to… (moveToLogic.openMoveToModal with the card's FileSystem entry), Cut, Copy, and Delete (deleteDashboardLogic.showDeleteDashboardModal). It is a click-triggered actions dropdown, not a right-click context menu.
    proof_type: [test, visual]
    edge_cases:
      - EC-11a [must] "Move to…" appears only when the card's FileSystem entry is resolved (entryByRef) [test]
      - EC-11b [must] "Paste into this folder" lives on the breadcrumb row, shown only with a non-empty buffer (REQ-08) [test]
      - EC-11c [nice] menu near viewport edge → quill DropdownMenu repositions on-screen [visual]
      - EC-11d [must] Move to… opens the canonical searchable FolderSelect modal (moveToLogic), not a bespoke picker [test]
      - EC-11e [must] item deleted by another user → action 404s gracefully [test]
      - EC-11f [must] Delete → canonical confirm + "also delete insights" modal (deleteDashboardLogic), defined cascade [test]
      - EC-11g [nice] keyboard access to the dropdown trigger + items [test, manual]
      - EC-11h [must] right-click on multi-selection → DEFERRED (multi-select not built, REQ-09) [test]
      - EC-11i [must] permission-denied user → destructive actions follow existing model/delete-modal guards [test]

  - id: REQ-12  priority: must-have
    description: copy=duplicate preserves correct dashboard semantics (tiles, sharing, subscriptions) by reusing the canonical duplicate
    happy_path: copy+paste calls dashboardsModel.duplicateDashboard({ duplicateTiles: true }) so the copy inherits exactly the established Duplicate behavior (no new sharing/subscription handling); CH-03 is honored by reuse. The copy lands in its default (Unfiled) folder — target-folder placement is DEFERRED (see EC-08c).
    proof_type: [test]
    edge_cases:
      - EC-12a [must] duplicate zero-tile dashboard → clean empty duplicate [test]
      - EC-12b [nice] duplicate many tiles (max) → all copied, no truncation [test]
      - EC-12c [must] duplicate shared/public → sharing NOT silently inherited (CH-03) [test]
      - EC-12d [must] duplicate with active subscriptions → NOT silently copied (CH-03) [test]
      - EC-12e [must] duplicate then delete source → duplicate independent (deep copy) [test]
      - EC-12f [nice] tiles referencing soft-deleted insights → graceful, no crash [test]
      - EC-12g [must] name collision in target → disambiguated by existing duplicate behavior [test]
      - EC-12h [must] team/project isolation → duplicate stays in same team [test]

  - id: REQ-13  priority: must-have
    description: Writes delegate to existing infra (single source of truth); sidebar stays consistent
    happy_path: every mutation delegates — move → projectTreeDataLogic.moveItem, "Move to…" → moveToLogic, duplicate/rename → dashboardsModel, delete → deleteDashboardLogic, new folder → api.fileSystem.create; FileSystem rows are the single source of truth, so the sidebar reflects changes.
    proof_type: [test]
    edge_cases:
      - EC-13a [must] explorer move updates sidebar without manual refresh (shared moveItem path) [test]
      - EC-13b [must] folder created in sidebar appears in the explorer and vice versa (folder rows reloaded) [test]
      - EC-13c [must] rollback on server error reverts BOTH body and sidebar [test]
      - EC-13d [nice] undo of a move restores both views (moveItem undo) [test]
      - EC-13e [must] concurrent writes from body + sidebar → no duplicate calls, consistent [test]
      - EC-13f [must] folder deleted in sidebar while explorer drilled into it → navigates up / degrades, no stale pane [test]
      - EC-13g [must] new folder created via api.fileSystem.create → loadFolderEntries refetch + navigate into it; failure surfaces a toast [test]

  - id: REQ-14  priority: DEFERRED
    description: "[DEFERRED — not built] \"Not a fan? tell us\" feedback affordance in the explorer arm only"
    happy_path: the explorer shows a lightweight feedback control; control does not; captures qualitative feedback, no exposure-leaking toggle. Not built on the current branch; edge cases retained for the later increment.
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
    description: Generic dashboard / folder type-icons in the explorer (v1, no thumbnails)
    happy_path: explorer cards use IconDashboard / IconFolder; consistent across all dashboards.
    proof_type: [visual, manual]
    edge_cases:
      - EC-15a [must] folder (IconFolder) vs dashboard (IconDashboard) icons distinguishable [visual]
      - EC-15b [nice] renders at all sizes/viewports [visual]
      - EC-15c [must] icon present even when metadata partially missing (name falls back to "Untitled"), never broken-image [test, visual]
      - EC-15d [nice] "too samey" manual judgment flag [manual]

  - id: REQ-16  priority: DEFERRED
    description: "[DEFERRED to the measurement increment] Event `dashboard opened from list` {ms_since_list_loaded, used_search, clicks_before_open, open_source}"
    happy_path: opening a dashboard from the list fires exactly one event with those props; open_source in {root, folder, search}. Not instrumented on the current branch — adoption (REQ-17/REQ-28) became the primary, so opened-from-list is the time-to-open secondary, moved to the measurement increment. Edge cases retained.
    proof_type: [test]
    edge_cases:
      - EC-16a [must] open without search → used_search=false, open_source != search [test]
      - EC-16b [must] open via search → open_source=search, used_search=true [test]
      - EC-16c [must] idle-tab ms → raw or capped per defined contract (idle cap is in the metric) [test]
      - EC-16d [must] same dashboard opened twice → two events (or defined dedupe), ms from list load each time [test]
      - EC-16e [must] open_source enums exactly the documented set per arm (root | folder | search — `grouped` retired with the grid arm) [test]
      - EC-16f [must] clicks_before_open at 0 and large → accurate [test]
      - EC-16g [must] keyboard open (Enter) → event fires with correct props [test]
      - EC-16h [must] list never finished loading → ms from a defined anchor, not NaN/negative [test]
      - EC-16i [must] event carries $feature/dashboards-list-view + project group [test]
      - EC-16j [must] navigation away before flush → event still captured (fired pre-nav) [test]
      - EC-16k [must] clock skew/negative elapsed → clamped >= 0 [test]

  - id: REQ-17  priority: must-have
    description: Event `dashboard moved to folder` {from_path, to_path} — the load-bearing primary-metric (adoption) signal
    happy_path: a successful move fires the event once on the SHARED, arm-agnostic projectTreeDataLogic move path, so every move (drag, per-card menu, "Move to…", clipboard) and every arm count toward folder-organization adoption identically; props are from_path + to_path.
    proof_type: [test]
    edge_cases:
      - EC-17a [must] fires on a real move regardless of trigger (drag / menu / Move to… / clipboard) — single shared path [test]
      - EC-17b [must] props are from_path + to_path; `method` + `multi_select_count` are DEFERRED (shared path can't attribute the interaction) [test]
      - EC-17c [must] fires once per move, not per render [test]
      - EC-17d [must] failed/rolled-back move does NOT fire (no false positives) [test]
      - EC-17e [must] no-op move (same folder, isValidMove=false) does NOT fire [test]
      - EC-17f [must] bulk move count → DEFERRED with multi-select (REQ-09) [test]
      - EC-17g [must] carries project group + $feature (wired in the measurement increment) [test]

  - id: REQ-18  priority: DEFERRED
    description: "[DEFERRED to the measurement increment] Folder lifecycle events `dashboard folder created|renamed|deleted`"
    happy_path: create/rename/delete a folder from the explorer fires the corresponding single event. Not emitted on the current branch (folder create/delete delegate to api.fileSystem.create / deleteDashboardLogic without a dedicated analytics event yet). Edge cases retained.
    proof_type: [test]
    edge_cases:
      - EC-18a [must] explorer vs sidebar create → no double-count (CH-07) [test]
      - EC-18b [must] no-op rename does NOT fire renamed [test]
      - EC-18c [must] failed delete (403/409) does NOT fire deleted [test]
      - EC-18d [must] delete folder w/ dashboards → single delete event (not per child) per contract [test]
      - EC-18e [nice] rapid create-then-delete → both fire in order [test]
      - EC-18f [must] all three carry project group + $feature [test]

  - id: REQ-19  priority: DEFERRED
    description: "[DEFERRED to the measurement increment] Event `dashboards clipboard action` {action (cut|copy|paste), result (move|duplicate), item_count}"
    happy_path: each clipboard op fires; cut/copy carry action+item_count; paste carries result=move|duplicate. Not emitted on the current branch — the clipboard works (REQ-08) but a paste resolving to a move still fires the shared `dashboard moved to folder` event (REQ-17), so adoption is captured; the dedicated clipboard analytics event is deferred. Edge cases retained.
    proof_type: [test]
    edge_cases:
      - EC-19a [must] action enum cut|copy|paste; result only on paste [test]
      - EC-19b [must] item_count matches selection (1 and N) [test]
      - EC-19c [must] failed paste → defined (failure marker or none), no phantom success [test]
      - EC-19d [nice] cut then cut (overwrite) → two cut events, latest count [test]
      - EC-19e [must] paste resolving to no-op move → consistent with REQ-17 no-op rule [test]
      - EC-19f [must] carries project group + $feature [test]
      - EC-19g [must] empty-buffer paste fires NO event [test]

  - id: REQ-20  priority: DEFERRED
    description: "[DEFERRED — depends on REQ-14] Event `dashboards view feedback` from the \"not a fan?\" affordance"
    happy_path: submitting feedback fires one event carrying arm/variant context. Not built (the affordance itself, REQ-14, is deferred). Edge cases retained.
    proof_type: [test]
    edge_cases:
      - EC-20a [must] fires only in non-control arms [test]
      - EC-20b [must] double-submit → exactly one event [test]
      - EC-20c [must] carries $feature + project group [test]
      - EC-20d [nice] unicode/HTML text carried/escaped safely [test]
      - EC-20e [nice] network failure → retry, not double-counted [test]

  - id: REQ-21  priority: must-have
    description: First-open-success / anti-pogo-stick guardrail from existing pageview sequences (backtestable)
    happy_path: a find "succeeds" iff the first dashboard opened in a session is the one kept (no bounce-to-list + open of a DIFFERENT dashboard in-window); pogo-stick rate must not rise for explorer vs control.
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
    happy_path: share of list visits that open >= 1 dashboard in-session, per arm/project; must not drop for explorer vs control, esp. cold-start.
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
      - EC-25e [must] folder filed by an explorer member visible to all, but each renders their (same) arm [test]

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
    happy_path: project-level adoption proportion at a low single-digit baseline, per arm; ship/no-ship gated on this PLUS the guardrails; derived primarily from the shared `dashboard moved to folder` event (REQ-17). Explorer is compared to control to see how much the drill-in paradigm lifts organizing. Organizing depth (moves/creations per organizing project) is the supporting secondary.
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
    happy_path: ship explorer on an adoption lift over control with NO guardrail regression (first-open success, find-conversion, engagement); A-vs-explorer is the single ship/no-ship read; cold-start contingency (hold the ship / gate explorer on onboarding) honored.
    proof_type: [test, manual]
    edge_cases:
      - EC-30a [must] explorer beats control but pogo-stick regresses → NO-SHIP explorer (guardrail veto) [test]
      - EC-30b [must] explorer beats control but cold-start find-conversion drops → contingency (hold the ship / gate explorer on onboarding) [test]
      - EC-30c [n/a] RETIRED with the tree arm — explorer-vs-tree comparison [n/a]
      - EC-30d [nice] adoption result below the pre-registered MDE → require the powered threshold before ship [manual]
      - EC-30e [must] explorer null vs control → keep A, bank learning, no fishing [test, manual]
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

  # --- Requirements added in the explorer reframe (REQ-32 since retired with the tree arm) ---

  - id: REQ-32  priority: RETIRED
    description: "[RETIRED with the tree arm — built then cut before launch] Tree arm — persistent LemonTree folder panel beside the dashboards table, scoped recursively"
    happy_path: N/A — the persistent-tree paradigm was built (DashboardsTree panel + recursive subtree content) but cut before launch to keep the experiment a crisp two-arm A/B (it was a science arm, not a decision arm). The tree-exclusive code was removed (DashboardsTree, the currentSubtreeDashboards selector, the subtreeDashboards util, toggleFolder/collapsedFolders expand-state). The shared folder-rows data layer it once shared survives in REQ-37 (the explorer still needs empty folders + folderTree + folderSiblings). The empty-folder coverage lives on in EC-37a.
    proof_type: []
    edge_cases: []

  - id: REQ-33  priority: must-have
    description: Drag-a-dashboard-onto-a-folder to file it (explorer folder cards) via the shared dnd helper
    happy_path: dragging a dashboard card onto a folder (DroppableFolder) calls moveDashboardToFolder → projectTreeDataLogic.moveItem; the 10px mouse-activation distance keeps a plain click a navigation/open and only a longer drag a move; native link drag is cancelled so dnd-kit owns the gesture.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-33a [must] drop onto current/own folder → no-op (calculateMovePath isValidMove=false), no move event [test]
      - EC-33b [must] drop outside any folder → parseDashboardDragEnd returns null, cancels cleanly [test]
      - EC-33c [must] drag before folder rows load → entry missing; stays quiet while loading, otherwise warns (no silent no-op) [test]
      - EC-33d [must] move error → projectTreeDataLogic rollback (shared move path) [test]
      - EC-33e [must] plain click still navigates the card link, not a drag (activation distance) [test, visual-flow]
      - EC-33f [nice] touch-drag on tablet (250ms delay / 5px tolerance) → works or degrades to the per-card "Move to…" menu [manual, visual-flow]
      - EC-33g [must] keyboard/non-drag users have a move path via the per-card menu (REQ-11) [test, manual]

  - id: REQ-34  priority: must-have
    description: Explorer global name search flips to a flat results grid
    happy_path: when the shared filters bar has a non-empty search query, the explorer abandons folder navigation and renders a flat grid of all matching dashboards (dashboardsLogic.dashboards); clearing the query restores folder navigation.
    proof_type: [test, visual, visual-flow]
    edge_cases:
      - EC-34a [must] non-empty search.trim() → flat results grid, breadcrumb/folder cards hidden [test, visual-flow]
      - EC-34b [must] zero matches → "No dashboards match your search" message, not a blank grid [test, visual]
      - EC-34c [must] clearing search → returns to the previously-drilled folder (currentFolder preserved) [test, visual-flow]
      - EC-34d [must] whitespace-only query → treated as no search (trim) [test]
      - EC-34e [must] search result cards keep the per-card actions menu + rename [test]
      - EC-34f [must] search HTML/script injection rendered safe (REQ-07g) [test]

  - id: REQ-35  priority: must-have
    description: "\"New folder\" affordance (explorer) creates a folder inside the current folder"
    happy_path: a "New folder" button on the explorer breadcrumb row opens a name dialog; on submit, createFolder joins the name under currentFolder, calls api.fileSystem.create({type:'folder'}), reloads folder rows, navigates into the new folder, and toasts success.
    proof_type: [test, visual-flow]
    edge_cases:
      - EC-35a [must] empty/whitespace name → dialog field error, no create call (LemonDialog errors + createFolder trim guard) [test]
      - EC-35b [must] created at root vs inside a drilled folder → path = currentFolder + name [test]
      - EC-35c [must] api.fileSystem.create failure → error toast, no navigation, no phantom folder [test]
      - EC-35d [must] new empty folder appears immediately as a navigable/droppable target (folder rows reloaded) [test]
      - EC-35e [nice] unicode/emoji/long folder name accepted [test, visual]
      - EC-35f [must] folder-create analytics event (REQ-18) → DEFERRED [test]

  - id: REQ-36  priority: must-have
    description: "\"Move to…\" picker delegates to the canonical searchable FolderSelect modal (moveToLogic)"
    happy_path: the per-card "Move to…" action opens moveToLogic.openMoveToModal with the dashboard's FileSystem entry; the existing FolderSelect modal performs the move (no bespoke picker), so the sidebar stays consistent and the shared move event fires.
    proof_type: [test]
    edge_cases:
      - EC-36a [must] action shown only when the card's FileSystem entry is resolved (entryByRef) [test]
      - EC-36b [must] move via the modal fires the shared `dashboard moved to folder` event (REQ-17) [test]
      - EC-36c [must] cancel the modal → no move, no event [test]
      - EC-36d [must] move into the current folder → no-op per the modal's own handling [test]

  - id: REQ-37  priority: must-have
    description: Folder-rows data layer — load BOTH dashboard and folder FileSystem rows so empty folders appear
    happy_path: dashboardsFileSystemLogic loads type=dashboard rows (index each dashboard to its folder via ref) AND type=folder rows (so empty/just-created folders appear), then derives folderTree, folderContents/compactedSubfolders, and the breadcrumb / folderSiblings; dashboards with no row fall back to Unfiled/Dashboards. (The tree-exclusive subtreeDashboards derivation was removed with REQ-32.)
    proof_type: [test]
    edge_cases:
      - EC-37a [must] empty folder (folder row, no dashboards) → appears in folderTree + as a subfolder card in the explorer [test]
      - EC-37b [must] dashboard with no FileSystem row → grouped under Unfiled/Dashboards [test]
      - EC-37c [must] folder tree is stable-sorted (shallowest-first build, label localeCompare) [test]
      - EC-37d [must] ancestors of a deep folder all appear even if only the leaf has dashboards (addWithAncestors) [test]
      - EC-37e [must] >=500 dashboard or folder rows → single-page read, surplus dashboards fall back to Unfiled, console.warn on cap hit; pagination DEFERRED [test]
      - EC-37f [must] dashboard + folder row load run on mount (afterMount) and refetch after duplicate/new-folder [test]
      - EC-37g [must] folder rows load failure → toast error, structure degrades to Unfiled, no crash (loadDashboardFileSystemEntriesFailure) [test]
      - EC-37h [nice] malformed row (missing path/ref) → skipped/Unfiled, no crash [test]

SUMMARY:
  total_requirements: 37 (REQ-04, REQ-05, REQ-32 retired; REQ-33..37 ship with the explorer arm)
  live_requirements: 34 (37 total − 3 retired: REQ-04, REQ-05, REQ-32)
  arms: control | explorer (grid and tree both retired)
  built_on_current_branch: REQ-01,02,03,06,07,08,10,11,12,13,15,17,33,34,35,36,37 (foundation + explorer arm + folder-rows layer + load-bearing move event)
  deferred (measurement increment / later): REQ-09 (multi-select), REQ-14 (feedback affordance), REQ-16 (opened from list), REQ-18/19/20 (folder-lifecycle / clipboard / feedback events), the REQ-17 method+multi_select_count props, copy=paste target-folder placement, pagination
  retired_with_grid_arm: REQ-04, REQ-05
  retired_with_tree_arm: REQ-32 (built then cut before launch)
  measurement/analysis (not UI): REQ-21,22,23,24,25,26,27,28,29,30,31
  priority (rule-applied, confirm at checkpoint): must-have core ~ REQ-01,02,03,06,07,08,10,11,12,13,17,21,22,23,24,25,26,27,28,30,31,33,34,35,36,37; nice-to-have REQ-15,29 + flagged [nice] edge cases; DEFERRED REQ-09,14,16,18,19,20; RETIRED REQ-04,05,32
```
