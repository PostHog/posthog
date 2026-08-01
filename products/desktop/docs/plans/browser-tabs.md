# PRD: Browser Tabs for the Channels Canvas Surface

Status: ready-for-agent
Surface: Channels space (`/website/*`) — the canvas surface with the `< >` nav and "Go back to Code" / "Leave feedback" chrome.

## Problem Statement

When working in the Channels space, a person can only look at one canvas at a time. Opening a second canvas replaces the first; there is no way to keep several canvases at hand, jump between them, or compare two side by side. The `< >` history is global to the window and mixes unrelated navigations together, so "back" is unpredictable. Nothing about which canvases were open survives a restart. People who live in this surface lose their working set every time and cannot arrange canvases the way a browser lets them arrange tabs.

## Solution

A browser-style tab strip across the top of the Channels space, rendered in the title bar exactly like the provided mockup: macOS traffic lights, a history/clock control, `< >` back/forward, a row of pill tabs (each an optional icon + a text label, active tab elevated/white, inactive tabs muted/gray), and a `+` to open a new tab.

- Each tab is an open canvas. Clicking a canvas focuses its tab if already open in the window, otherwise opens a new one.
- Tabs can be dragged to reorder within the strip.
- A tab can be torn off into a **new OS window** (multi-window) via a menu action ("Move to new window" / "Open in split"), giving a true side-by-side split. Focus moving between windows updates each window's own nav chrome to reflect where you are.
- Back/forward behaves like a per-window action timeline: navigations within a tab are traversable, and when a tab's actions are exhausted, traversal spills back to the previously focused tab — all without opening or closing any tab.
- The open tabs, their order, and the window layout persist. On relaunch, the full session (all windows, their tabs, and the active tab in each) is restored.
- A per-tab `scroll_state` slot is reserved now (column present, unwired) so scroll restoration — and other per-tab state — can land later without a migration.

## User Stories

1. As a Channels user, I want a tab strip in the title bar, so that I can see all my open canvases at once.
2. As a Channels user, I want each tab to show the canvas name as its label, so that I can tell tabs apart.
3. As a Channels user, I want each tab to show an optional icon derived from the canvas template, so that I can recognize a canvas type at a glance.
4. As a Channels user, I want the active tab visually elevated (white) and inactive tabs muted (gray), so that I always know which canvas I'm looking at.
5. As a Channels user, I want to hover a tab and see which channel it belongs to, so that I can disambiguate tabs from different channels sitting side by side.
6. As a Channels user, I want a single global strip where canvases from different channels coexist, so that my working set isn't fragmented per channel.
7. As a Channels user, I want a `+` button, so that I can open a new tab quickly.
8. As a Channels user, I want clicking a canvas in the grid or sidebar to focus its existing tab if it's already open in this window, so that I don't accumulate duplicates.
9. As a Channels user, I want to open the same canvas in two different windows, so that I can reference it while working elsewhere.
10. As a Channels user, I want to close a tab, so that I can tidy my working set.
11. As a Channels user, I want closing the last tab in a secondary window to close that window, so that empty windows don't linger.
12. As a Channels user, I want closing the last tab in the primary window to show the channels landing, so that I always have a home to return to.
13. As a Channels user, I want to drag tabs to reorder them within the strip, so that I can arrange my working set.
14. As a Channels user, I want to move a tab to a new OS window via a menu action, so that I can view two canvases side by side.
15. As a Channels user, I want each window to have its own nav chrome reflecting its active tab, so that switching focus between windows tells me where I am.
16. As a Channels user, I want the `< >` buttons to walk a per-window action timeline, so that back/forward is predictable within a window.
17. As a Channels user, I want navigations made inside a tab to be traversable with `< >`, so that I can step back through what I did in that tab.
18. As a Channels user, I want back to spill to the previously focused tab once the current tab's actions are exhausted, so that the whole window's history is reachable.
19. As a Channels user, I want back/forward to only move focus and never open or close tabs, so that opening a tab and pressing back returns me to the prior tab while the new tab stays open.
20. As a Channels user, I want back/forward to skip entries pointing at tabs I've since closed, so that the timeline doesn't strand me on dead canvases.
21. As a Channels user, I want switching to a visible/split tab to be instant, so that side-by-side work feels responsive.
22. As a Channels user, I want background tabs to be re-run on return rather than kept live forever, so that many open tabs don't exhaust memory.
23. As a Channels user, I want my open tabs and their order to survive an app restart, so that I resume exactly where I left off.
24. As a Channels user, I want every window I had open to reopen at its saved position with its tabs and active tab, so that my multi-window layout is restored.
25. As a Channels user, I want my tab changes in one window to reflect immediately in any other window, so that the windows never disagree about my working set.
26. As a Channels user on the web, I want tabs and "new window" to work via a browser window, so that the feature isn't desktop-only.
27. As a developer, I want a reserved per-tab scroll slot, so that scroll restoration can be added later without a schema migration.
28. As a Channels user, I want a history/clock control in the strip, so that I can access recent navigation (surface present per mockup; behavior scoped to the action timeline).

## Implementation Decisions

### Scope
- Tabs front the existing sandboxed-iframe canvases in the Channels space only. The Code-workspace panel system (`panelLayoutStore`, split/moveTab) is untouched and out of scope.
- No webview is introduced; "browser tabs" is the framing, not literal web browsing.

### Tab + window domain model (durable)
- New core service **`TabsService`** (`@injectable`, host-neutral, domain state in `zustand/vanilla`) owns the set of open tabs and the window registry. It is the single source of truth.
- Persistence is reached through an **injected workspace-client slice**, never directly. On desktop that slice is backed by a workspace-server SQLite table via Drizzle; on web it is backed by a remote workspace-server / PostHog API behind the same interface.
- Two tables:
  - `browser_tabs`: `id`, `dashboard_id`, `channel_id` (nullable), `window_id` (FK), `position`, `scroll_state` (JSON, nullable, **reserved/unwired**), `created_at`, `last_active_at`.
  - `browser_windows`: `id`, `bounds` (JSON), `is_primary`, plus ordering/active-tab pointer.
- A tab stores **references only**; display is resolved at render: label = `dashboard.name`; icon = the existing template-derived icon (`iconForTemplate(templateId)`), optional; channel hover = `channel.name` resolved via `channel_id`.
- `position` is gap-spaced integers, reindexed on collision. Concurrent reorders reconcile via SQLite-as-source plus the emit/subscription fan-out below.

### Cross-window coordination (reuse existing transport — no new bus)
- All renderer windows share a single main-process container, so they already talk to one hub via tRPC-over-IPC.
- Live sync reuses the established `TypedEventEmitter` → tRPC `.subscription()` → renderer pattern (as used by `connectivity`). Any window mutates → `TabsService` writes through the persistence slice and emits → the subscription fans the change out to every window.
- No bespoke window-to-window messaging and no new event-bus abstraction is introduced.

### Multi-window (net-new host capability)
- The host gains a window manager: today the app is single-window (`window.ts`) and the platform exposes only a single-window interface. This grows into create/track/focus/bounds for multiple `BrowserWindow`s, behind a `@posthog/platform` interface with a per-host adapter (Electron adapter; web adapter uses `window.open`).
- **Sequencing of drag:** in-strip drag-reorder ships in this PRD. Tearing a tab into a new OS window ships via a **menu action** ("Move to new window" / "Open in split") that spawns the window programmatically. Literal drag-the-tab-out-of-the-window-to-spawn is explicitly a follow-up (it requires native pointer tracking and main-process cursor-position window creation; HTML5 DnD does not cross OS windows).

### Back / forward — per-window tab-tagged action stack
- Modeled as a per-window chronological action stack where each entry is tagged with its `tab_id`; the active tab is derived from the current pointer.
- Implemented on top of the existing TanStack router history per renderer (tag entries with `tab_id`, derive active tab from the current entry) rather than a parallel history engine.
- Switching tabs **pushes** a new entry (so back returns to the prior tab). `< >` only moves the pointer; it never creates or destroys tabs. Entries whose `tab_id` no longer exists are skipped during traversal.
- Stack is **per-window**; each window's `< >` walks only its own actions. Action stacks are not persisted across relaunch (fresh `< >` per launch; tabs/windows themselves are restored).

### Live-iframe policy — cap by visibility
- Replace the flat 2-frame warm pool with a visibility policy: visible / split-pane tabs stay live; background tabs are evicted after a threshold and re-run on return. Pools are per-window.

### Scroll
- Deferred. There is no host-level scroll to capture (the channels layout is `overflow:hidden` and all scrolling lives inside the null-origin iframe). Real restoration requires a new sandbox postMessage contract (iframe reports `scrollY`; host re-applies after render) and is out of scope here. The `scroll_state` column is created now so the follow-up needs no migration.

### Lifecycle
- Dedup per window (click focuses an existing tab in that window); duplicates allowed across windows.
- Closing the last tab in a secondary window closes the window; closing the last tab in the primary window shows the channels landing.

### UI (matches the mockup, quill primitives)
- Tab strip renders in the title bar: traffic-light region, a history/clock control, `< >` back/forward, the pill tab row, and a `+` button.
- All controls are `@posthog/quill` `Button`s — icon buttons use `size="icon-sm"` with an outline/ghost variant for the `< >`, clock, and `+`; the `< >` reuse the existing disabled-when-unavailable logic. Channel-on-hover uses quill `Tooltip`. Active vs inactive pill styling (elevated white vs muted gray) is applied via className on the tab element. Icons come from `@phosphor-icons/react` (same set as `iconForTemplate`).

## Testing Decisions

Good tests assert **external behavior at a seam**, not internal wiring. We test at the three highest existing seams:

1. **`TabsService` (core)** — unit-tested with faked injected dependencies (a stubbed workspace-client persistence slice and a fake emitter), mirroring `packages/core/src/focus/service.test.ts`. Assert observable behavior: open dedups within a window but allows cross-window dupes; close removes the row and (for secondary windows) signals window close; mutations persist through the slice and emit a change; restore reconstructs windows + tabs + active pointers from persisted state.
2. **Pure action-stack + tab transforms** — pure-function tests with no DI, mirroring `packages/core/src/panels/panelLayoutTransforms.test.ts`. Cover: reorder (gap-spacing + collision reindex), dedup resolution, tab-tagged push on switch, pointer-only back/forward, skipping entries for closed tabs, and the spill-to-previous-tab boundary.
3. **`TabStrip` presentational component (ui)** — props-in/render-out, with a Storybook story and an RTL test like `packages/ui/src/primitives/NestedButton.test.tsx`. Assert: active/inactive styling reflects the active prop; clicking a tab/`+`/`< >` fires the right callback; disabled `< >` when no history; tooltip surfaces the channel name. Data-fetching is excluded from the component (tRPC/host queries don't resolve in Storybook), so the strip is pure-presentational and fed resolved tab view-models.

The window-manager platform adapter and the SQLite slice are covered by their host/integration layers, not unit tests of `TabsService`.

## Out of Scope

- Literal drag-a-tab-out-of-the-window to spawn a new OS window (this PRD ships tear-off via a menu action; drag-out is a follow-up).
- Scroll restoration inside a canvas (column reserved; sandbox postMessage contract is a follow-up).
- Tabs in the Code workspace or any non-Channels surface.
- A real webview / arbitrary-URL browser.
- Persisting the back/forward action stack across relaunch.
- A standalone "history/clock" recent-navigation panel beyond the action timeline (the control is surfaced per the mockup; richer history UI is later).
- Drag a tab into the Code-workspace pane system.

## Further Notes

- The visual target is the provided title-bar mockup: traffic lights, clock, `< >`, two pill tabs (inactive gray with a dotted/spinner-style icon, active white with a target/scan-style icon), and `+`. The active/inactive treatment and optional-icon-plus-text shape are requirements.
- Web portability is a first-class constraint: the same `TabsService`, persistence interface, and subscription pattern apply; only the adapters differ (Electron window manager + SQLite vs `window.open` + remote workspace-server/API). Desktop ships first; web adapters keep web a port, not a rewrite.
- Cross-window focus must update each window's nav chrome ("where we are"); because each window is a full renderer with its own chrome, this is largely automatic once the active tab per window drives the breadcrumb.
