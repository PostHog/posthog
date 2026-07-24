# Browser tabs (Channels canvas surface)

A browser-style tab strip in the Channels title bar (`/website/*`), each tab
fronting an open **canvas, task, or channel sub-section** (a `TabIdentity`:
`dashboardId | taskId | channel(+section) | blank`).
This file documents the UX and the model; edit it when the behaviour changes.

Canvases and tasks are equal citizens: navigating to either
(`/website/$channelId/dashboards/$dashboardId` or
`/website/$channelId/tasks/$taskId`) replaces the active tab's target in place,
the label resolves from the canvas name or the task title, and switching back
returns to whichever the tab points at. `setTabTarget` is the in-tab-nav
primitive for both.

Channel sub-sections are tabs too: the header nav (`Inbox`, `Artifacts`,
`Recents`, `CONTEXT.md` — see `canvas/channelSections.ts`) routes to
`/website/$channelId/<section>`, which is identified by `channelId` +
`channelSection`. The tab labels by the section (`Inbox`) with a `#` icon; the
channel home (`/website/$channelId`, no section) labels by the channel name.
Every channel tab's hover leads with `#<channel>` then the page name (the home
tab, whose label already is the channel, shows just the one line). Switching
sections is an in-tab replace — one channel tab, the section is sub-navigation
within it — because the identity differs only by `channelSection`.
Dedup/identity keys on all four fields, so two channels' inboxes (or one
channel's inbox vs artifacts) are distinct tabs.

## Where the logic lives

The feature is deliberately split so the rules are portable and testable:

- **`@posthog/shared` (`browser-tabs.ts`, `browser-tabs-schemas.ts`)** — pure,
  host-neutral logic: the domain shapes (`BrowserTab` / `BrowserWindow` /
  `TabsSnapshot` / `TabTarget`), the transforms (`openOrFocusTab`, `newBlankTab`,
  `setTabTarget`, `closeTab`, `closeTabs`, `setTabOrder`), `decideTabNavigation` (what a
  location change means for the strip), and the snapshot predicates
  (`primaryWindow`, `activeTabIsBlank`, `primaryWindowHasNoTabs`) the `/website`
  index uses to choose the new-tab screen over a first-channel redirect. No
  React, no I/O. This is where behaviour is unit-tested. Back/forward is driven by
  router history + `decideTabNavigation`, not a separate action stack.
- **`@posthog/workspace-server` (`services/browser-tabs/`, `db/`)** — the
  authoritative single-instance `BrowserTabsService` in the main process. Owns
  the durable snapshot in sqlite (`browser_tabs` / `browser_windows`), applies
  the shared transforms, and emits `snapshotChange` for cross-window fan-out.
  The repo persists the whole snapshot as a transactional full replace.
- **host-router (`routers/browser-tabs.router.ts`)** — one-line forwards over the
  service + the snapshot subscription. Renderer calls it via `useHostTRPC`;
  resolved from the main container (bound in `apps/code` main `di`).
- **`@posthog/core` (`browser-tabs/browserTabsStore.ts`)** — renderer mirror of
  the snapshot, seeded once and kept live by the subscription.
- **this folder (`@posthog/ui`)** — `BrowserTabStrip` (container; mounted in the
  Channels title bar in `router/routes/__root.tsx`), `TabStrip` (presentational),
  `BlankTabView` (the new-tab placeholder), `TaskTabIcon` (sidebar-parity status
  icon for task tabs), the client facade, the boot contribution that seeds +
  subscribes the store, and **`tabsSync.ts` — the local-first sync policy**:
  every operation applies its shared pure transform to the renderer mirror
  synchronously (interactions are instant; new tabs mint their id client-side
  so no navigation ever waits on IPC), server writes are background persistence,
  and while any write is in flight remote snapshot pushes are dropped because
  they may predate newer local state. If a push was dropped, the renderer
  re-fetches the authoritative snapshot after the write batch settles so a real
  mutation from another window is retained; otherwise the last settling write
  applies its returned snapshot. This makes rapid tab switching race-free
  without losing cross-window updates.

One source of truth: any window mutates → service writes sqlite + emits → every
window's store updates. No window talks to another directly. The same shape ports
to web: a remote workspace-server + the subscription over WS, only the adapters
differ. Desktop ships first.

## UX

### The strip
- Lives in the Channels title bar, after a `#title-bar-left` section sized to the
  Channels sidebar width so the strip starts flush with the content pane.
- Each tab is a quill `Button` (variant `default`). The active tab is elevated;
  inactive tabs are muted. Tabs **shrink to fit** — the strip never scrolls
  (`overflow-hidden`, pills `flex-1 basis-[200px]` capped at `max-w-[200px]`).
- Labels **fade** at the right edge (a CSS mask, not an ellipsis). The close
  affordance reveals on hover; on hover the button gains right padding so the
  label shrinks and its fade follows, clearing room for the close button.
- Icon: a canvas tab uses the template icon (`iconForTemplate`); a task tab uses
  `TaskTabIcon` — the **same status icon as the sidebar** (cloud run status, PR
  state, generating / unread / pinned / needs-permission), so a tab and its
  sidebar row never drift.
- Hover shows a tooltip with the name and (if any) the channel. All tab tooltips
  share one `TooltipProvider` so moving across tabs shows each instantly.
- The **active tab's name + highlight follow the current route / history state**
  — they update the instant you navigate, not after the server snapshot
  round-trips (see Gotchas).

### Opening, replacing, the new-tab page
- **Navigating while a tab is active replaces that tab's target in place**
  (in-tab navigation) — it does *not* open or dedup-focus another tab.
- **New tabs come only from `+`.** `+` opens a **blank tab** (no target); the
  content pane renders a quill `<Empty>` "new tab page" (`BlankTabView`).
  Navigating to a canvas/task while the blank tab is active fills it in.
- `openOrFocusTab` **dedups per window** on the full target (canvas or task);
  the same target may be open in different windows.

### Closing
- Closing the active tab focuses its neighbour.
- Closing the last tab of a **secondary** window closes the window; closing the
  last tab of the **primary** window empties the strip and lands on the
  **new-tab screen** at `/website` — it does *not* jump to the first channel
  (see Gotchas).

### Context menu & pinning
- Right-click on a pill opens a quill `ContextMenu`: **Pin/Unpin tab**, then
  **Close tab / Close other tabs / Close tabs to the right / to the left**.
  Bulk items disable when they would close nothing.
- Bulk closes go through one `closeMany` procedure backed by the `closeTabs`
  transform, which **composes `closeTab`** so the per-window succession rules
  live in one place. The UI computes the id list from the strip's **displayed**
  (pinned-first) order and passes the right-clicked tab as the `focusTabId`
  anchor; when the active tab is among those closed, focus follows the anchor
  rather than `closeTab`'s stored-order neighbour (which could be a pinned tab
  at the far end of the strip).
- **Pinned tabs are view state, not domain state**: ids live in
  `pinnedTabsStore` (zustand `persist` → localStorage). Pinned tabs collapse to
  an **icon-only** pill (label moves to the tooltip; the `#channel / home`
  hover still applies), sort to the front of the strip, hide the hover close,
  and are skipped by every bulk close. Stale pins are pruned against the live
  snapshot; unpinning re-homes the tab to the front of the unpinned block
  (`frontOfUnpinnedOrder`), applied optimistically so it doesn't double-jump.
- **Single-renderer assumption.** Pins are per-origin: the desktop app is
  single-window, so there is no live cross-window sync of pins. For the web
  host (multiple browser tabs share the origin) a `storage`-event listener
  keeps renderers roughly in step, but the pin-protection on bulk close is a
  renderer-side filter — the `closeMany`/`closeTabs` service layer is
  pin-agnostic (pins never leave the renderer). The canonical tab **order**
  stays pin-agnostic in SQLite; only rendering applies the pinned-first
  partition.

### Drag to reorder
- Pills are `@dnd-kit/react` sortables (x-axis–locked, full-opacity preview),
  split into two sortable groups so a drag can't cross the pinned boundary.
- The in-flight preview lives in a **transient view store** (`tabReorderStore`),
  never in the domain snapshot mirror: `dragover` reorders the previewed
  *stored* order **within the dragged tab's pin group only** (`reorderWithinGroup`
  — the other group's stored slots are untouched, so the pinned-first partition
  is never baked into stored positions), and the strip renders it. `dragend`
  persists the final stored order via `setOrder`/`setTabOrder` (identity-
  preserving) after optimistically applying it; a cancel just drops the
  preview. Keeping the preview out of the mirror means a concurrent server
  snapshot push mid-drag can't clobber it and the app shell doesn't re-render
  per `dragover`.

### Back / forward (the action timeline)
- Every router history entry is **tagged with the tab it belongs to** (`tabId` in
  `HistoryState`, via module augmentation).
- **Switching tabs adds history.** Going from tab A to tab B and pressing
  **back** returns to A; pressing **forward** returns to B.
- **Back walks one shared, tab-tagged timeline.** Navigations made *within* a
  tab are tagged with that tab, so back first steps through the current tab's
  own history; **once the current tab has no more history, back continues into
  the previous tab** (and forward replays the other way).
- `< >` only move the focus pointer — they never open or close tabs. The active
  tab is derived from the current history entry; entries for tabs you've since
  closed are skipped.

### Cross-window & persistence
- Tabs, order, and windows persist to sqlite; the full session (all windows +
  their tabs + active tab) is restored on launch.
- Per-tab `scrollState` is reserved but **unwired** — scroll restoration is a
  later follow-up (it needs a sandbox postMessage contract; the canvas iframe is
  null-origin so the host can't read scroll).

## Gotchas / implementation notes

- **History state inherits across plain navigations.** A plain `navigate` (e.g.
  the sidebar) carries the current entry's `tabId` forward, so an in-tab nav
  arrives *tagged with the active tab*. `decideTabNavigation` therefore treats a
  tag as a "switch" **only when it differs** from the active tab; an equal tag
  falls through to a route-based replace. Getting this wrong makes in-tab
  navigation silently noop (the tab reverts on switch-away).
- **Stamp with `loc.href`.** When stamping a history entry, use the full
  `router.history.location.href` (a string). Reconstructing `pathname + search`
  crashes — `search` is parsed to an object at runtime ("Cannot convert object
  to primitive value"), which trips the error boundary and breaks persistence.
- **Active tab is derived from history state, not the server snapshot.** The
  history `tabId` flips instantly on navigate; the server `activeTabId`
  round-trips. The strip prefers history for "which tab is active" and resolves
  the active tab's label from the *route* target so the name/highlight don't lag
  a navigation behind.
- **Label resolution is reactive + cached.** Names come from the active
  record's warm fetch, then the channel list / all-tasks list, then a
  module-level cache — and the `tabs` memo references those sources directly (so
  biome's exhaustive-deps doesn't strip them and labels stay reactive).
- **Tab rendering is a wrapper `div` + Button + sibling close button.** The close
  cannot nest inside the Button (button-in-button is invalid + fails a11y lint);
  it's an absolutely-positioned sibling. The wrapper is `flex` so it hugs the
  button height (a block wrapper adds an inline line-box ~2px taller).
- **The `/website` index must not redirect to `channels[0]` while a blank tab is
  active or the strip is empty.** The blank `+` tab and the closed-all-tabs state
  both park at `/website`, whose `WebsiteChannelsIndex` otherwise `<Navigate>`s to
  the first channel. That puts a channel in the route, so `decideTabNavigation`
  opens a tab for it — hijacking the blank tab to `channels[0]`, or silently
  re-filling a strip the user just emptied. It's guarded with `activeTabIsBlank`
  (blank `+` tab) and `primaryWindowHasNoTabs` (closed-all → render
  `BlankTabView`), plus an `onIndexPath` check: TanStack renders this *stale*
  index for a couple of frames **after** the URL has already left `/website`
  (the `__root` Outlet un-suppresses on the way to `/website/$channelId` before
  the matched leaf settles), and that stale render must not redirect.
- **All writes are local-first (`tabsSync.ts`).** Close/open/new/reorder apply
  their shared transform to the mirror and navigate in the same tick; the
  `/website` index therefore always renders against post-mutation state and
  can't redirect (re-opening a tab) mid-flight. Mutation results and
  subscription pushes are never applied while writes are in flight — only the
  last settle reconciles. Don't add a mutation `onSuccess` that calls
  `setSnapshot`; route new writes through `applyLocalTransform` +
  `persistWrite`.

## Testing

- **Pure behaviour** is tested in `@posthog/shared` (`browser-tabs.test.ts`):
  open/dedup, close (neighbour / secondary-window / primary-landing),
  `closeTabs` (bulk close + anchor focus), `setTabOrder`, `newBlankTab`,
  `setTabTarget` (canvas + task), and
  **`decideTabNavigation`** — which encodes the activate / replace / open /
  stamp / noop decision the strip makes on every navigation (including "back
  returns to the previous tab" and the inherited-tag in-tab case) — plus the
  snapshot predicates (`activeTabIsBlank`, `primaryWindowHasNoTabs`,
  `primaryWindow`) that gate the index's new-tab-screen-vs-redirect choice.
  `BrowserTabStrip`'s effect dispatches that decision, so the tested function is
  the one that runs.
- **Presentational** rendering is tested in `TabStrip.test.tsx` (active styling,
  select, close-without-select, new-tab).
- Full back/forward integration across the real router belongs in an E2E
  (Playwright) spec, not a unit test.

## Split view (parked — how to approach it)

A working prototype (July 2026, since removed — recoverable from git history)
let a pill be dragged off the strip onto right/bottom drop zones over the
content area, splitting the scene into a resizable two-pane
`react-resizable-panels` group. What we learned, for whoever picks it up:

- **The constraint:** one TanStack Router = one location = one `<Outlet>`.
  Two panes can't both be routes. Three ways out, in order of preference:
  1. **Router-less target pane** (what the prototype did): the secondary pane
     renders the tab's target directly by id. `WebsiteDashboard` already takes
     `dashboardId` as a prop and `TaskDetail` takes a `task` (replicate the
     cache-first fetch from `routes/website/$channelId/tasks/$taskId.tsx`) —
     both mount standalone today. **Channel views (inbox/artifacts/…) are the
     blocker**: they read route params/loaders throughout, so they need a
     props-parameterization pass before they can render in a pane. That
     refactor is most of the remaining work.
  2. **Second router over memory history** — renders any route, but needs a
     chrome-less root and confuses the tab-strip navigation effect
     (`decideTabNavigation` assumes one router).
  3. **Tear-off to a second OS window** — the tabs data model already supports
     it (`browser_windows`, secondary-window close semantics in
     `closeTab`/`closeTabs`); Electron-only.
- **Wiring that already exists and stays:** `BrowserTabsDndProvider` wraps the
  channels chrome, so drop zones over the content area just register
  `useDroppable` targets in the same scope; pill drag data is
  `{ type: "browser-tab", tabId }`. The prototype's pieces were a persisted
  `splitViewStore` (identity + direction + transient `isDraggingTab`), a
  `TabSplitLayout` wrapper around the outlet box in `__root.tsx`, and a
  split-zone branch in the provider's `dragend`.
- **UX decisions already settled:** zones are right 35% / bottom 35%
  (non-overlapping), a second drop replaces the split, a blank tab is
  rejected, the split persists across relaunch, and a header X closes it.
- **Open questions for the real version:** should the split pane get its own
  tab strip (it probably wants the panels feature's tree model instead of a
  single-pane store); how does the active-tab highlight relate to the
  secondary pane; and whether in-pane navigation should be possible at all
  without a router.

## Known rough edges / follow-ups

- Content is rendered by the route `<Outlet>` while the strip's active tab is
  store state. An in-tab content replace followed by `back` can briefly show a
  route/tab mismatch. Tightening this means rendering the target by the active
  tab's id rather than the route.
- Drag-to-reorder is wired (see **Drag to reorder** above). Tear-off to a new
  OS window is still unwired.
- Many pinned tabs overflow the strip: pinned pills are incompressible and the
  tablist only `overflow-hidden`s (so they clip within the strip rather than
  overlap the title bar). A scrollable / overflow-menu strip is a follow-up.
- Scroll restoration (the reserved `scrollState`) is unwired.

## Dev note

Changes to the main process (a new migration, service method, or router
procedure) or to `@posthog/shared` (vite pre-bundles it) need a **`pnpm dev`
restart** to run live — HMR alone won't apply them.
