# Mobile friendliness of the Max UI

> **Source:** outstanding_items.md § 6 (Item 6) · **Locus:** frontend — responsive layout
> **Effort:** M (refined down from M-L: the scene is fewer files than feared, and most width offenders share one constant) · **Priority:** Lowest (user-stated) · **Blocks rollout:** No
> **Joins:** Standalone. No sibling item shares this locus. It is a self-contained frontend responsive pass over the Max scene (`frontend/src/scenes/max/`) plus the side-panel mount (`frontend/src/layout/navigation-3000/sidepanel/SidePanel.tsx`). Sequence it **last**, after the rollout-relevant items (G1–G8) land, because it touches the broadest set of components and carries the highest visual-regression-snapshot churn.

## Problem

The Max (PostHog AI) chat UI is built for desktop. On a narrow viewport — phone, tablet portrait, or a deliberately-shrunk browser — it renders poorly:

- The thread and composer are centered columns capped at a fixed pixel width (`max-w-180` = 45rem = 720px). On a viewport narrower than ~720px the column still works (it falls back to `w-full`), but nothing below that switches layout, font scale, or chrome density. The cap is the only width signal and there is no narrow-screen branch.
- When Max runs in the right-hand **side panel**, the panel has hard pixel minimums (`DEFAULT_WIDTH = 512`, compact minimum `330`). On a small screen the panel either eats most of the viewport or, clamped to `windowSize.width`, leaves almost no room for the underlying app — it was never designed to become a full-screen overlay on mobile.
- The scene uses **container queries** (`@container/thread`, `@md/thread:`) for a couple of margin tweaks, but uses **zero viewport breakpoints** — no Tailwind `sm:`/`md:`/`lg:` prefixes and no window-size hook anywhere in `frontend/src/scenes/max/`. So the layout cannot react to the actual screen size, only to the width of its own container (which is itself unconstrained on mobile).

Net effect: the chat is usable but cramped/awkward on phones; the side-panel variant is effectively unusable on a phone-width viewport.

This is **lowest priority** and **does not block rollout** — it is polish. It should be explicitly deferred until the higher-priority sandbox-migration items land, both because they may move the very components this pass restyles and because shipping snapshot-heavy CSS churn first would create noisy rebase conflicts for those PRs.

## Current behavior (verified)

All line numbers below were opened and confirmed on 2026-06-13. The doc's cited lines were accurate (no drift) except where noted.

**Fixed-width column (the dominant offender — one literal, four sites):**

- `frontend/src/scenes/max/Thread.tsx:239` and `:254` — both the sandbox and LangGraph thread wrappers use the identical class string `'@container/thread flex flex-col items-stretch w-full max-w-180 self-center gap-1.5 grow mx-auto'`. (Doc cited `:239,254` — correct.)
- `frontend/src/scenes/max/components/QuestionInput.tsx:232` — composer container: `(isSticky || isThreadVisible) && 'sticky bottom-0 z-10 max-w-180 self-center'`. (Doc cited `:232` — correct.)
- `frontend/src/scenes/max/components/SidebarQuestionInput.tsx:70` — the pending-form/approval branch wrapper: `'w-full max-w-180 self-center px-3 mx-auto …'`.

These four `max-w-180` sites must line up — thread body and composer share the same centered column so it reads as one chat surface.

**Other hardcoded widths in the scene (audit results):**

- `frontend/src/scenes/max/components/AiFirstMaxInstance.tsx:165` — full-page chat column uses a _different_ cap, `max-w-3xl` (48rem/768px), collapsing to `max-w-none` once there are messages (`:166`). Note: full-page Max and side-panel Max use two different width systems (`max-w-3xl` vs `max-w-180`); a responsive pass should reconcile or at least not regress this.
- `frontend/src/scenes/max/components/AiFirstMaxInstance.tsx:47` — `w-100` (25rem/400px) on a header sub-element.
- `frontend/src/scenes/max/components/AILiabilityNotice.tsx:20` — `max-w-160` (40rem).
- `frontend/src/scenes/max/HistoryPreview.tsx:27` — `max-w-120` (30rem).
- `frontend/src/scenes/max/ConversationHistory.tsx:57` — `max-w-screen-lg` (already viewport-relative; fine).
- `frontend/src/scenes/max/components/MaxChangelog.tsx:64` — `min-w-[280px] max-w-[320px]` (a popover; lower priority).
- `frontend/src/scenes/max/Context.tsx:260,322,356` — `max-w-20`/`max-w-48` on context chips (these are truncation caps, intentional; leave alone).
- `frontend/src/scenes/max/Thread.tsx:1531` — `min-h-[200px]`, `:1585` — `w-64` sidebar inside the multi-visualization modal; `Thread.tsx:1501` — `LemonDialog … maxWidth: 1400`. These live in a modal, not the chat column; lower priority.
- The pervasive `min-w-0`/`flex-1`/`truncate` usages (e.g. `Thread.tsx:578,1144,1172`, `Context.tsx`) are correct flexbox-overflow guards — **do not touch**; they are what makes the existing column degrade gracefully rather than overflow.

**Side-panel mount:**

- `frontend/src/layout/navigation-3000/sidepanel/SidePanel.tsx:80-81` — `const DEFAULT_WIDTH = 512` and `const SIDE_PANEL_MIN_WIDTH_COMPACT = 330`. (Doc cited `:80-81` — correct.)
- `:138-144` — width is computed as `Math.max(desiredSize ?? DEFAULT_WIDTH, SIDE_PANEL_MIN_WIDTH_COMPACT)`, then clamped to `Math.min(rawSidePanelWidth, windowSize.width)`. So on a 360px phone the panel is forced to ≥330px and then clamped to 360px — it nearly covers the whole screen but is not a true full-screen overlay, and the resizer (`:178`) is still active.
- `:185-186` — there is **already** a `lg:hidden` click-outside overlay (`<div onClick={() => closeSidePanel()} className="lg:hidden fixed inset-0 -z-1" />`), so the codebase already treats `< lg` as "mobile" for the side panel. This is the precedent to extend.
- `SidePanel.tsx` already imports and uses `useWindowSize` — import at `:17`, hook call at `:136` (`const { windowSize } = useWindowSize()`), and the destructured `windowSize.width` consumed at `:144`. Note: only `windowSize` is currently destructured; `isWindowLessThan` is **not** pulled out yet (`grep isWindowLessThan` in this file returns nothing), so the mobile branch must add it to the existing destructure. The responsive primitive is already in this file.

**Breakpoint reality (important correction to the task framing):**

- There is **no `useBreakpoint` hook in the repo.** `grep -rl useBreakpoint frontend/src` returns 0 files. The task brief (and the triage doc's framing) reference "PostHog's useBreakpoint hook" — that hook does not exist. The actual primitive is **`useWindowSize`** at `frontend/src/lib/hooks/useWindowSize.ts`, which returns `{ windowSize, isWindowLessThan(breakpoint) }` and accepts an optional `widthOffset` (used by the side panel to subtract its own width).
- Two breakpoint sources exist and **disagree on `sm`**:
  - CSS Tailwind prefixes (`sm:`/`md:`/`lg:`) come from `common/tailwind/tailwind.config.js:805-812`: `sm: 576px, md: 768px, lg: 992px, xl: 1200px, 2xl: 1600px`.
  - The JS constant `TAILWIND_BREAKPOINTS` (`frontend/src/lib/constants.tsx:648-654`), which `useWindowSize` reads, is: `sm: 526, md: 768, lg: 992, xl: 1200, 2xl: 1600`.
  - `md`/`lg`/`xl`/`2xl` match; **`sm` differs (526 vs 576).** So `isWindowLessThan('sm')` (526) is NOT equivalent to the CSS `max-sm:` (<576). Pick `md` or `lg` as the mobile cutoff (they agree across both systems) and avoid `sm` to sidestep the mismatch. This plan uses `md` (768px) as the "phone/narrow tablet" cutoff.
- Confirmed precedent for the chosen primitives:
  - Pure Tailwind responsive prefixes: `frontend/src/queries/nodes/WebVitals/WebVitalsTab.tsx` (`hidden sm:flex`, `sm:hidden`, `hidden sm:block`) and `frontend/src/lib/components/FilterBar.tsx` (`md:flex-row`, `max-sm:flex-col`, `max-sm:max-h-[500px]`).
  - `useWindowSize` for imperative branching: `frontend/src/layout/navigation-3000/sidepanel/SidePanel.tsx` itself.

## Approach

**Two-layer strategy — Tailwind prefixes by default, `useWindowSize` only where layout must branch structurally.**

1. **Default to Tailwind responsive utility prefixes** (`md:`/`lg:`) for everything that is a pure presentational tweak (widths, padding, font scale, show/hide chrome). This is the dominant repo convention (WebVitalsTab, FilterBar), is zero-JS, snapshot-stable, and honors CLAUDE.md "prefer tailwind utilities over inline styles." No hook, no kea state, no re-render cost.

2. **Use `useWindowSize` only where the layout must change structure**, i.e. the side-panel-→-overlay decision in `SidePanel.tsx`, which already imports `useWindowSize` and already uses a `lg:hidden` overlay. We extend the existing imperative width computation rather than introduce a new mechanism. We do **not** branch the panel/overlay decision in a kea logic — see "Decisions" for why this React-hook usage is the correct, convention-aligned choice here and not a violation of the "avoid React hooks" rule.

**Reconciling with CLAUDE.md "avoid React hooks / business logic in kea logics":** that rule targets _business_ logic — data fetching, state machines, mutations. Viewport-derived presentational state is not business logic, and the repo's own answer to it is `useWindowSize` (a thin `useSyncExternalStore` wrapper) plus Tailwind prefixes, used directly in components including `SidePanel.tsx`. There is no kea pattern for window size in this codebase, and inventing one (a `windowSizeLogic` with a resize listener) would be net-new infrastructure for a lowest-priority polish task. So: lean on Tailwind prefixes (no hook at all) wherever possible; use the existing `useWindowSize` hook for the one structural branch; do **not** build a kea logic for breakpoints.

**Mobile model for each mount:**

- **Full-page Max** (`/ai`, via `AiFirstMaxInstance` → `ChatArea` and `MaxInstance`): already roughly fluid (`w-full`, `grow`, `mx-auto`, caps that collapse to `max-w-none` with messages). Work here is incremental: ensure horizontal padding shrinks on narrow screens (`px-4` → `px-2` at `<md`), the column cap (`max-w-180` / `max-w-3xl`) never causes side-clipping (it can't — it's a `max-`, not a fixed `w-`), and the composer's absolutely-positioned send/mic cluster (`QuestionInput.tsx:418-424`) doesn't collide with content at narrow widths.
- **Side-panel Max** (right-hand panel): on `< md`/`< lg`, the panel should become a **full-width overlay** (cover the viewport) instead of a 330–512px column squeezing the app. Reuse the existing `lg:hidden` click-outside overlay; add a width branch so that when `isWindowLessThan('md')` (or align to the existing `lg` overlay cutoff) the panel width becomes `100vw` (full overlay) and the resizer is hidden/disabled. This is the single highest-impact fix.

**Rejected alternatives:**

- _New `useBreakpoint` hook (as the task brief literally suggested)._ Rejected: it does not exist, and `useWindowSize` already covers the need. Adding a parallel hook fragments the convention.
- _Container queries everywhere (`@md/thread:` style)._ The scene already uses these for the thread, and they are great for _intra-component_ density. But the side-panel-overlay decision depends on the **viewport**, not the container (the container would report the panel's own narrow width and can't tell "phone" from "narrow desktop panel"). Container queries can't drive "go full-screen on a phone." So: keep/extend container queries for in-thread density tweaks, but the overlay decision must be viewport-based.
- _A kea `windowSizeLogic`._ Rejected as over-engineering for polish; no such logic exists and `useWindowSize` is the established answer.
- _Touching the `min-w-0`/`truncate`/flex guards._ Rejected — those are the existing graceful-degradation scaffolding; removing them would _cause_ overflow.

## Implementation steps

Ordered highest-impact-first, so each step is independently shippable and the early ones deliver most of the value.

1. **Side-panel → full-width overlay on small screens (biggest lever).** In `frontend/src/layout/navigation-3000/sidepanel/SidePanel.tsx`:
   - Extend the existing `const { windowSize } = useWindowSize()` destructure at `:136` to also pull `isWindowLessThan` (currently only `windowSize` is destructured — `isWindowLessThan` is unused so far, so this is a one-line change, not a new hook call). Define `const isMobile = isWindowLessThan('md')` (768 — agrees across both breakpoint systems).
   - When `isMobile`, set the rendered panel width to the full viewport (`sidePanelWidth = windowSize.width`) and skip the `Math.max(..., SIDE_PANEL_MIN_WIDTH_COMPACT)` floor so it doesn't get clamped to a column.
   - Hide/disable the `<Resizer>` (`:178`) when `isMobile` — a full-screen overlay shouldn't be drag-resizable.
   - The existing `lg:hidden` click-outside overlay (`:185-186`) already closes the panel on tap-outside; verify it still makes sense at the `md` cutoff or align both to one cutoff (recommend `< lg` to match the existing overlay — see Decisions).
   - Verify `panelLayoutLogic.setSidePanelWidth(sidePanelWidth)` (`:148`) being the full width doesn't break the main-content layout math (the main scene is hidden behind the overlay anyway on mobile).

2. **Unify and make-fluid the chat column constant.** Introduce a single shared class fragment for the centered chat column so the four `max-w-180` sites stay in lockstep. Either:
   - Extract a `const MAX_CHAT_COLUMN = 'w-full max-w-180 self-center mx-auto'` exported from a small shared module (e.g. `frontend/src/scenes/max/max-constants.tsx`), and reuse it in `Thread.tsx:239,254`, `QuestionInput.tsx:232`, `SidebarQuestionInput.tsx:70`; **or**
   - Leave them inline but apply the same responsive padding change to all four.
     Then add narrow-screen padding: the column currently has no horizontal padding of its own (padding comes from `Max.tsx`/`AiFirstMaxInstance.tsx` wrappers via `px-4`/`p-3`). Reduce those wrapper paddings at `<md` (e.g. `px-4 md:px-4 px-2` → use `px-2 md:px-4`) so the chat uses more of a phone's width. `max-w-180` itself needs no change (it's a _max_, already yields `w-full` below 720px).

3. **Composer narrow-screen audit (`QuestionInput.tsx`).**
   - The send/mic button cluster is absolutely positioned (`:418-424`, `bottom-[7px] right-[7px]`) and the textarea reserves `pr-12`/`pr-20` (`:377-378`, `:391`). Confirm at ~320px width the reserved padding still clears the buttons and the context chips row (`ContextDisplay`, `:399`) wraps rather than overlapping. If the hands-free `pr-20` is too tight on phones, bump the textarea bottom padding at `<md`.
   - Confirm the sticky composer (`sticky bottom-0`) sits correctly above the mobile browser chrome (it does, via normal flow; just verify no `100vh` trap).

4. **Secondary width offenders.** Apply responsive caps where a fixed cap could clip on phones:
   - `AiFirstMaxInstance.tsx:47` `w-100` → `w-full max-w-100` or `w-full sm:w-100` so it shrinks below 400px.
   - `AiFirstMaxInstance.tsx:165` reconcile `max-w-3xl` with the `max-w-180` used elsewhere (decide one canonical chat width — see Decisions).
   - `AILiabilityNotice.tsx:20` `max-w-160` is already `w-full max-w-160` (fine; verify padding).
   - `HistoryPreview.tsx:27` `max-w-120 w-full` (fine).
   - Leave `Context.tsx` chip caps and the multi-viz modal (`Thread.tsx:1501,1531,1585`) for a follow-up — they are not on the primary chat path and the modal already has `width: '90%'`.

5. **In-thread density (optional, container-query layer).** The thread already has `@md/thread:ml-10`/`@md/thread:mr-10` (`Thread.tsx:486`). If message bubbles feel cramped on phones, add `@container/thread`-scoped tweaks (smaller side margins below `@md`). This is pure polish and can be skipped in v1.

6. **Snapshot + story pass.** Update/extend `frontend/src/scenes/max/Max.stories.tsx` with a narrow-viewport story (set the Storybook viewport / a wrapping width) so visual-regression covers the mobile layout going forward.

## Files to change

| Path                                                                             | Change                                                                                                                                                                               |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `frontend/src/layout/navigation-3000/sidepanel/SidePanel.tsx`                    | Full-width-overlay branch for `< md`/`< lg` via existing `useWindowSize`; hide resizer on mobile; reuse the existing `lg:hidden` click-outside overlay. **Step 1 — highest impact.** |
| `frontend/src/scenes/max/Thread.tsx`                                             | Use the shared chat-column class at `:239` and `:254`; optional `@container`-scoped density below `@md`.                                                                             |
| `frontend/src/scenes/max/components/QuestionInput.tsx`                           | Shared chat-column class at `:232`; narrow-screen textarea bottom padding / button-cluster clearance audit.                                                                          |
| `frontend/src/scenes/max/components/SidebarQuestionInput.tsx`                    | Shared chat-column class at `:70`.                                                                                                                                                   |
| `frontend/src/scenes/max/max-constants.tsx` _(optional)_                         | Export `MAX_CHAT_COLUMN` shared class fragment.                                                                                                                                      |
| `frontend/src/scenes/max/components/AiFirstMaxInstance.tsx`                      | `w-100` → fluid at `:47`; reconcile `max-w-3xl` vs `max-w-180` at `:165`; responsive wrapper padding.                                                                                |
| `frontend/src/scenes/max/Max.tsx`                                                | Responsive wrapper padding (`px-2 md:px-4`) on `SceneContent`/welcome containers (`:54,118-120,225`).                                                                                |
| `frontend/src/scenes/max/components/AILiabilityNotice.tsx`, `HistoryPreview.tsx` | Verify/adjust fluid caps + padding (likely no change).                                                                                                                               |
| `frontend/src/scenes/max/Max.stories.tsx`                                        | Add a narrow-viewport story for snapshot coverage.                                                                                                                                   |

No backend, serializer, viewset, `lib/api`, or generated-type changes — **`/improving-drf-endpoints` and `/adopting-generated-api-types` do not apply.** This is pure frontend CSS/layout.

## Decisions & open questions

1. **Breakpoint cutoff for "mobile" — `md` (768) or `lg` (992)?**
   - _Recommendation:_ Use **`lg` (992)** for the **side-panel overlay** decision, to match the _existing_ `lg:hidden` click-outside overlay already in `SidePanel.tsx:186` (a 700px-wide phone-in-landscape or a small tablet running a 512px panel beside a ~200px app sliver is a bad experience, so `< lg` → overlay is reasonable). Use **`md` (768)** for chat-column **padding/density** tweaks (full-page Max at 800px is fine with a wide column). Both values agree across the CSS config and the JS constant, so `isWindowLessThan` and `lg:`/`md:` prefixes stay consistent. **Avoid `sm`** (526 vs 576 mismatch).
2. **One chat width or two?** Full-page Max uses `max-w-3xl` (768px); side-panel/thread use `max-w-180` (720px).
   - _Recommendation:_ Pick `max-w-180` as the single canonical chat-column width and apply it everywhere for consistency, unless design wants the full-page chat slightly wider. Either way, extract one shared constant so they never drift again. (Note: if design prefers keeping the wider full-page cap, the spacing scale already defines `192: '48rem'` — `max-w-192` is the exact spacing-scale equivalent of `max-w-3xl` (768px), so the shared constant can use a single numeric scale either way.)
3. **Does the floating Max input (`floatingMaxPositionLogic.tsx`) need a mobile pass?** It positions a floating composer.
   - _Recommendation:_ Out of scope for v1 unless QA finds it broken on phones; note it as a follow-up. (It's a separate surface from the side panel and full-page scene.)
4. **Resizer behavior on mobile:** hide entirely vs disable-but-show.
   - _Recommendation:_ Hide it (`!isMobile && <Resizer .../>`). A full-screen overlay has nothing to resize against.
5. **Is mobile even a supported target for PostHog AI today?** The product is desktop-first.
   - _Recommendation:_ Treat this as "don't break on small screens" rather than "build a mobile-first chat." Scope to: side-panel overlay + fluid column + composer clearance. Skip deep mobile-only features (e.g. swipe gestures). Confirm with the product owner before investing in step 5.

## Dependencies & sequencing

- **Within this pass:** Step 1 (side-panel overlay) is independent and highest-impact — ship it first/alone if time-boxed. Step 2 (shared column constant) should precede steps 3–4 so width changes are made in one place. Steps 4–6 are incremental polish.
- **Cross-plan (defer behind these):** This is the **last** item in the roadmap (outstanding_items.md § 7). It should land **after** the rollout-relevant siblings, several of which restyle the very components this pass touches and would otherwise collide on snapshots and on the same lines of `Thread.tsx` / `QuestionInput.tsx`:
  - `G2-cancel-bail-button.md` — edits `QuestionInput.tsx` button/tooltip derivation (`:442-492`); let it land first to avoid churn on the same composer.
  - `G5-sandbox-tool-card-parity.md`, `G6-sandbox-notification-rendering.md`, `G7-sandbox-streaming-resilience.md` — add/restyle tool cards, notification bars (e.g. a resources-used bar above the composer), and status rows inside the thread column; any new chrome they add must also be width-audited, so doing mobile _after_ them avoids re-auditing.
  - No overlap with `G1` (sandbox sizing — backend), `G3` (serializer query cost — backend), `G4` (history conversion — backend/decision), `G8` (relay allowlist — backend). Those are not in this locus.
- No new shared infra is introduced, so there is no fan-out risk to other plans.

## Testing

- **Jest / component:** The scene's existing tests (`QuestionInput.test.tsx`, `max.test.ts`) are behavioral, not layout — they won't catch CSS. Add a focused render test only if a structural branch (overlay vs column in `SidePanel.tsx`) is extracted into a testable predicate; otherwise rely on snapshots.
- **Storybook visual-regression (primary safety net):** Add a narrow-viewport variant to `frontend/src/scenes/max/Max.stories.tsx` (and a side-panel-on-mobile story) so the responsive layout is snapshotted. Run the standard `storybook` visual-regression flow; review the diffs intentionally (this change _will_ produce many snapshot diffs — that's expected, gate the PR review on them).
- **Manual / Playwright (optional):** Drive `/ai` and the side-panel Max at 360px, 414px, 768px, 992px, and 1280px widths. Verify: side panel becomes a full overlay below the cutoff and the resizer disappears; the composer send/mic buttons never overlap text; the thread column uses the available width with sane padding; no horizontal scrollbar appears. A single Playwright spec parameterized over a few viewport widths (per CLAUDE.md "prefer parameterized tests") is the right shape if automated coverage is wanted, but given lowest priority, manual verification at the listed widths is acceptable for v1.
- **No query-count / backend tests** — no backend surface changes.

## Rollout / flagging

- **No feature flag needed.** This is CSS-only, fail-safe (worst case a width tweak looks slightly off, never a functional break), and improves the small-screen experience monotonically. Gating responsive CSS behind a flag would mean shipping two layout codepaths and double the snapshot maintenance — not worth it.
- **No telemetry needed** beyond what already exists. If the product owner wants to know whether mobile is used at all before investing further, that's a pre-work question answerable from existing PostHog AI usage data (viewport width on `$pageview`), not something this pass needs to instrument.
- **Deferred until higher-priority items land** (see Dependencies). Mark the ticket blocked-on G2/G5/G6/G7 to avoid snapshot/line collisions on `QuestionInput.tsx` and `Thread.tsx`.

## Effort & risk

- **Effort: M** (refined down from M-L). Step 1 (side-panel overlay) is ~half a day given the hook and overlay already exist. Steps 2–4 are mechanical class edits across ~6 files. The real cost is the **snapshot review**, not the code.
- **Main risks:**
  1. _Snapshot churn / review fatigue_ — the widest-blast-radius part. Mitigate by landing after the sibling restyles (G2/G5/G6/G7) so snapshots aren't re-baselined twice.
  2. _Breakpoint mismatch footgun_ — using `sm` (526 in JS vs 576 in CSS) would make `isWindowLessThan('sm')` and `sm:` disagree. Mitigated by standardizing on `md`/`lg`, which agree.
  3. _Side-panel overlay interacting with `panelLayoutLogic` width math_ (`SidePanel.tsx:108,148`) — pushing a full-viewport width into `setSidePanelWidth` could confuse the main-content rect calc; on mobile the main content is hidden behind the overlay so it's benign, but verify no layout-thrash on resize across the cutoff.
  4. _Lowest priority / scope creep_ — easy to over-build a "mobile chat." Hold the line at "don't break on small screens" (Decision 5).
