# Browser tabs

A browser-style tab strip in the title bar. **A tab is a location**: it stores an
`href`, plus the nav state that href cannot express (`viewState`). Any route can
be a tab — a space, a canvas, a task, `/inbox`, `/loops`, `/settings/$category`.
This file documents the UX and the model; edit it when the behaviour changes.

The rule everything else follows:

> **Navigation never changes which tab you're in. Back/forward may.**

So there is exactly one path that moves focus between tabs (a history entry
tagged with a different tab), and a plain navigation can never reach it.
Navigating while a tab is active replaces that tab's location in place;
`setTabTarget` is the in-tab-nav primitive.

**There is no dedup.** Navigating to a page another tab already shows does not
focus that tab, and opening the same page twice gives you two tabs, as in any
browser. Earlier versions deduped on a `TabIdentity`, which also made the strip
navigate off any route outside that identity's vocabulary (`/loops` and
`/archived` are both all-null through it, so they compared equal).

The identity fields (`dashboardId | taskId | channelId + channelSection |
appView`) survive **only as a label and icon cache**, written alongside the href.
Never compare them to decide where a tab is.

The strip is always present in the app shell. `useSpacesTabs` tells shortcut and
navigation owners when the spaces layout owns browser-tab behavior. It is not a
rollout gate.

## Components & styling

Components come from `@posthog/quill`; layout is `div`s with Tailwind. **Radix is
banned** — do not add `@radix-ui/themes` or `@radix-ui/react-*` to any file here. See
[UI Components](../../../../../AGENTS.md#ui-components) in the root `AGENTS.md` for the
mapping. The tab strip's remaining `Flex`/`Box`/`Text` imports are legacy; when your
change lands in one of those files, convert what you touch (`<Flex align="center"
gap="2">` → `<div className="flex items-center gap-2">`, `Text` → quill `Text`).

## Where the logic lives

The feature is deliberately split so the rules are portable and testable:

- **`@posthog/shared` (`browser-tabs.ts`, `browser-tabs-schemas.ts`)** — pure,
  host-neutral logic: the domain shapes (`BrowserTab` / `BrowserWindow` /
  `TabsSnapshot` / `TabLocation` / `TabViewState` / `RailVisit`), the transforms
  (`openTab`, `setTabTarget`, `closeTab`, `closeTabs`, `setTabOrder`),
  `decideTabNavigation` (what a location change means for the strip), and
  `primaryWindow`. No React, no I/O. This is where behaviour is unit-tested.
  Back/forward is driven by router history + `decideTabNavigation`, not a
  separate action stack.
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
  `TaskTabMarks` (a session tab's status dot, in the session
  list's vocabulary), the client facade, the boot contribution that seeds +
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
- Icon: a canvas tab uses the template icon (`iconForTemplate`); a session tab
  uses **the session list's status dot** (`TaskTabMarks` → `taskDot`), so a tab
  and its list row never say different things about the same session. The list's
  trailing identity badges are deliberately *not* carried over: a pill is
  `max-w-[200px]` and shrinking, and the name is what a tab is scanned for.
- Hover shows a tooltip with the name and (if any) the channel. All tab tooltips
  share one `TooltipProvider` so moving across tabs shows each instantly.
- The **active tab's name + highlight follow the current route / history state**
  — they update the instant you navigate, not after the server snapshot
  round-trips (see Gotchas).

### Opening, replacing, and blank tabs
- **Navigating while a tab is active replaces that tab's location in place**
  (in-tab navigation). It does *not* open or focus another tab, ever.
- **New tabs come only from explicit new-tab actions.** `+` and Cmd/Ctrl+T open
  `/activity`. Cmd/Ctrl-clicking a navigation destination opens that destination's
  root in a new tab (the rail in Spaces, the sidebar in the legacy layout).
- `openTab` always appends. There is no dedup to focus an existing tab.

### Closing
- Closing the active tab focuses its neighbour.
- Middle-clicking any tab closes it, including a pinned tab.
- Closing the last tab of a **secondary** window closes the window. Closing the
  last tab of the **primary** window replaces it with a fresh `/activity` tab.

### Keyboard
- **⌘1-9 switches tabs**, the browser way: 1-8 pick that position, 9 picks the
  last tab however many there are. It reads the **displayed** (pinned-first)
  order, so the key matches what you count on screen.
- Those keys have other owners elsewhere — starred spaces (`ChannelHotkeys`)
  and task switching (`GlobalEventHandlers`) — so both yield wherever the strip
  claims them, gated on the same `useSpacesTabs()`. Two owners firing on one
  press is worse than either.
- ⌘T opens a tab, ⌘W closes the active one.

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

### Per-tab nav state
Each tab carries the nav state its href cannot express, in `viewState`:

- `listOpen` / `spaceId` — which sidebar pane is drawn and the space it is drawn
  over, so two tabs can sit on different spaces with different sidebars.
- `lastByPane` — **where each rail destination was when this tab last left it.**
  A rail click navigates the active tab back to its own remembered href rather
  than to the destination's root. Per tab on purpose: a window-global memory
  would let one tab's rail click restore an href another tab established.
  Record and replay both go through `isRestorableVisitHref` (canvas `railPane.ts`), so a settings or redirect-alias href is never remembered and a stale stored one is never replayed.

`BrowserTabStrip`'s navigation effect is the **single writer for settled router
navigation**. It runs on every settled navigation, including the ones a rail
click does not make (hotkeys, deep links, links in the content), which is why a
note taken as you click away is not enough. Async completion can explicitly
retarget its originating background tab as described below. `railHistoryStore`
/ `RailHistorySync` were the window-global predecessors and are gone.

### In-flight task creation
- Submitting a new task snapshots the prompt and originating `tabId` before its
  first asynchronous preflight. Switching tabs cannot unmount the editor out
  from under task creation or change which prompt is sent.
- Pending, success, and failure routes replace the originating tab. When that
  tab is in the background, `setTabTarget({ activate: false })` updates its
  durable target without changing the active tab.
- New-task editor drafts are keyed by `tabId`. Two tabs on the same `/new` route
  can hold different prompts; successful submission or closing a tab clears
  only that tab's draft.

### Cross-window & persistence
- Tabs, order, windows, and each tab's `href` + `viewState` persist to sqlite;
  the full session (all windows + their tabs + active tab) is restored on launch.
  Desktop and web both seed `/activity` when the primary window has no tabs.
- `rewriteSavedLocation` (in `@posthog/shared`) runs over persisted hrefs on
  load, so a snapshot written before the routes were flattened does not restore
  tabs onto `/website/*` routes that no longer exist.
- Per-tab `scrollState` is reserved but **unwired**. Router history restores native
  page scroll for report visits and their source pages. Canvas iframe scrolling
  still needs a sandbox postMessage contract; the iframe is null-origin.

## Gotchas / implementation notes

- **History state inherits across plain navigations.** A plain `navigate` (e.g.
  the sidebar) carries the current entry's `tabId` forward, so an in-tab nav
  arrives *tagged with the active tab*. `decideTabNavigation` therefore treats a
  tag as a "switch" **only when it differs** from the active tab; an equal tag
  falls through to a route-based replace. Getting this wrong makes in-tab
  navigation silently noop (the tab reverts on switch-away).
- **A same-href tab switch must push history directly.** Router-level
  `navigate({ href })` may collapse a navigation when the selected tab has the
  same href as the active tab, leaving the old history `tabId` in place. Tab
  selection uses `pushTabHistoryEntry` so the selected tab identity changes
  even when its location does not.
- **Stamp with `loc.href`.** When stamping a history entry, use the full
  `router.history.location.href` (a string). Reconstructing `pathname + search`
  crashes — `search` is parsed to an object at runtime ("Cannot convert object
  to primitive value"), which trips the error boundary and breaks persistence.
- **Active tab is derived from history state, not the server snapshot.** The
  history `tabId` flips instantly on navigate; the server `activeTabId`
  round-trips. The strip prefers history for "which tab is active" and resolves
  the active tab's label from the *route* target so the name/highlight don't lag
  a navigation behind.
- **Tab selection writes history first.** A click must not optimistically focus
  the mirror or restore the target's `viewState` while the outgoing route is
  still settled. That transient pairing lets the navigation effect write the
  outgoing href into the selected tab. Selection only pushes the target's
  tagged history entry; that settled entry drives view-state restore,
  activation, and durable focus through the navigation effect. The sidebar may
  project the tagged target's stored `viewState` while navigation is pending,
  but that projection is render-only: it must not write stores or trigger
  visibility side effects such as marking the projected space seen.
- **The effect reconciles SETTLED state only (`settledLocation.ts`).** During a
  pending navigation the router's `location` is already the destination while
  `resolvedLocation` (and `matches`, and so `params` / `railPane`) still describe
  the page being left. Read the href from one and the tab tag from the other and
  the effect is told "tab B is on tab A's href", which it writes to B — this is
  the "switching tabs rewrites another tab's URL" corruption, and it has been
  reintroduced twice by changing one selector and not the other. `settledLocation`
  returns the pair from one snapshot and marks it current only when both the
  href and tab owner match the in-flight entry. The effect must skip every write
  until that happens: even a harmless-looking `stamp` would otherwise replace
  the new entry's tab owner with the outgoing tab. The in-flight `location`
  still drives the strip's **highlight**, which should flip instantly — that is
  a render, not a write.
- **A session is not always a path param.** Activity reads its picked item out
  of `/activity`'s *search*. The strip's identity and label therefore come from
  `useActiveSession()`, never `params.taskId`, or a tab sitting on an open
  session reads "New tab". That selection lives in the URL precisely so a tab
  can name it and restore it — don't move it back into a store.
- **A saved search names its own tab.** `/feeds/$feedId` is the tab; picking a
  result reads that task into the pane without leaving the search, so the strip
  drops the active session there and labels the tab with the search's name.
- **Label resolution is reactive + cached.** Names come from the active
  record's warm fetch, then the channel list / all-tasks list, then a
  module-level cache — and the `tabs` memo references those sources directly (so
  biome's exhaustive-deps doesn't strip them and labels stay reactive).
- **Tab rendering is a wrapper `div` + Button + sibling close button.** The close
  cannot nest inside the Button (button-in-button is invalid + fails a11y lint);
  it's an absolutely-positioned sibling. The wrapper is `flex` so it hugs the
  button height (a block wrapper adds an inline line-box ~2px taller).
- **`/spaces` is a page, not a redirect.** It used to bounce to `channels[0]`.
  The rail can land there and return to it, so don't reintroduce the redirect.
- **All writes are local-first (`tabsSync.ts`).** Close/open/new/reorder apply
  their shared transform to the mirror and navigate in the same tick. Mutation
  results and subscription pushes are never applied while writes are in flight —
  only the last settle reconciles. Don't add a mutation `onSuccess` that calls
  `setSnapshot`; route new writes through `applyLocalTransform` + `persistWrite`.

## Testing

- **Pure behaviour** is tested in `@posthog/shared` (`browser-tabs.test.ts`):
  `openTab` (always appends, never dedups), close (neighbour /
  secondary-window / primary-landing), `closeTabs` (bulk close + anchor focus),
  `setTabOrder`, `setTabTarget` (href + view state + label cache move together),
  `primaryWindow`, `setWindowActiveTab`, and **`decideTabNavigation`** — the
  activate / replace / open / stamp / noop decision the strip makes on every
  navigation, including the two cases href-matching exists for (two routes
  outside the label vocabulary, and a search-param-only change).
  `BrowserTabStrip`'s effect dispatches that decision, so the tested function is
  the one that runs.
- **Presentational** rendering is tested in `TabStrip.test.tsx` (active styling,
  select, close-without-select, new-tab).
- Full back/forward integration across the real router belongs in an E2E
  (Playwright) spec, not a unit test.

## Tiled tabs (split view)

Tabs can share the content pane side by side or in a grid, the way Arc splits
a space. The feature lives in `features/tab-tiling/`; this section documents
the model and the UX so both stay in step with the code.

### The model (`tileLayout.ts`)
- A **group** is a tree. Leaves are tab ids; inner nodes split their children
  along one axis (`horizontal` = side by side, `vertical` = stacked) and carry
  optional `sizes` in percent. Two tabs beside each other are one horizontal
  split; a 2x2 grid is a horizontal split of two vertical splits.
- `tileTab` places a tab on an edge of the tile that shows another tab. When
  the target's parent already splits on that axis the new leaf becomes a
  sibling, so three tabs in a row stay one flat split. A tab that was tiled
  elsewhere is removed from its old group first. A group stops accepting drops
  at `MAX_TILES_PER_GROUP` (4).
- `untileTab` removes a leaf, collapses a split left with one child, and
  dissolves a group left with one tile. `pruneGroups` applies that to every
  tab missing from the live snapshot.
- Groups are **view state** in `tileLayoutStore` (zustand `persist` →
  localStorage), like pins: tab ids are durable in SQLite so a split survives
  relaunch, and the model is pure so the tree transforms are unit-tested in
  `tileLayout.test.ts`.

### Rendering (`TileLayout.tsx`)
- **The constraint:** one TanStack Router = one location = one `<Outlet>`.
  `TileLayout` wraps the outlet in `__root.tsx`. When the active tab belongs
  to a group, the whole group renders as nested `react-resizable-panels`
  groups and the **outlet renders inside the active tab's tile**. Every other
  tile renders its tab **without the router** (`TileTabContent`): a task tab
  mounts `TaskDetail` from the cache-first fetch, a dashboard tab mounts
  `WebsiteDashboard`. Pages that read route params (channel views, settings)
  cannot mount that way yet; their tile shows a notice with a button that
  activates the tab instead.
- Activating a tab in a group shows the group with the outlet moved to that
  tab's tile. Tabs outside a group show alone, as before.
- Each tile has a `ChromeBar` header with an X that removes it from the split.
  A background tile shows icon and name. The active tile shows what its page
  pushes to the header store (the editable title) and, on a task, the
  `TaskHeaderActions` row; a page that pushes nothing shows the tab name.
  **The header is the only place that switches the active tab.** A click
  inside a background page never moves the outlet out from under it.
- The pane-wide header rows (`ContentHeader`, `SpaceHeaderRow`) hide while
  the active tab is in a group (`useActiveTabTiled`): one title above several
  tiles named the wrong thing, and the active tile's header carries it now.
- Resizes persist through `onLayout` → `setSplitSizes`, which returns the same
  array for an unchanged layout so the mount-time callback writes nothing.

### The split in the strip
A split is one thing you switch to, so the strip shows it as **one pill**, the
way Arc, Chrome and Edge nest split tabs under one entry. Vivaldi leaves tiled
tabs unmarked and scattered in its bar, and that is its most-requested fix.
- `collapseSplits` (`displayOrder.ts`) keeps one pill per group in the slot of
  its first member in the display order (the **anchor**); the other members
  leave the strip. The pill's `id` is the anchor, so reorder and the
  sortable slot work as for one tab.
- The pill leads with a miniature of the split: the members' icons in a
  framed row, in tile order. Its label and icon follow the tile that was
  active last (`tileLayoutStore.activeByGroup`, written by `TileLayout` on
  every activation), so the pill always names the page you would land on.
  The tooltip reads `Split view` and lists every member.
- **Click the pill to come back to the split** after visiting another tab; it
  reopens on that last-active tile (`lastActiveIn`). A click while the split
  is on screen does nothing.
- The pill's X, middle-click and `Close split` close every tab of the split.
  Removing one tab is the tile header's X, and Cmd/Ctrl+W closes the active
  tile only. Bulk closes count a split pill as one slot but close all of its
  tabs. `Separate all tabs` in the pill's menu dissolves the group and keeps
  the tabs. A split pill has no pin item.
- Cmd/Ctrl+1-9 count the split pill as one stop.

### Drag to tile
- While a pill is dragged (`tabReorderStore.draggingTabId`), every tile of the
  visible group, or the lone active page, shows four edge drop zones
  (`TileDropZones`, `useDroppable` in the same `BrowserTabsDndProvider` scope,
  data `{ type: "tile-drop", tabId, edge }`). The dragged tab's own tile shows
  none, and a full group disables its zones. A split pill drags as one unit
  and a pinned pill stays icon-only, so neither shows zones, and `dragend`
  refuses a tile drop for them.
- Pill drags stay x-axis locked; the zones are still hit because dnd-kit's
  default collision detection tests the **pointer** position first.
- `dragend` on a tile zone calls `tileTab` and returns without persisting the
  strip order, because the pill never left its slot.
- Analytics: `Browser tab tiled` (`edge`, `tile_count`) and
  `Browser tab untiled` (`tile_count`).

### Follow-ups
- Channel views in background tiles need a props-parameterization pass.
- No in-tile navigation without a router: a link inside a background tile
  drives the one router, so it changes the active tile's page, not its own.
  A second router over memory history is the known alternative.
- Tiles cannot be rearranged inside a split yet (the pill drags as one unit);
  keyboard focus between tiles is also open.

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
