# PRD: Browser tabs in the spaces layout

Status: decided, not built
Surface: the whole app under `channelsLayout` (spaces / project-bluebird), not just `/spaces/*`
Supersedes the decisions in [browser-tabs.md](./browser-tabs.md), which describes the strip as it shipped
into the pre-rail layout. That document stays as the record of what was built; this one records what changes.

## Problem Statement

The tab strip is switched off in the spaces layout. `__root.tsx` renders it only when `channelsLayout`
is false; with the layout on, its slot in the title bar holds the command search bar instead. So the
surface that grew a nav rail, a space sidebar and a flattened route tree is also the surface with no
way to keep more than one thing open.

Meanwhile the spaces layout grew its own answer to "put me back where I was": `railHistoryStore`
records the last href per rail destination, and a rail pick restores it. That is a second
remember-where-you-were system sitting beside the tabs snapshot, scoped per window rather than per
tab. The two cannot both be right once tabs are on.

## Solution

Tabs come back, in both layouts, and become the app's only unit of "a place you are". A tab owns a
route and the nav state that route cannot express. Everything that used to remember a location per
window now remembers it per tab.

The governing rule:

> **Navigation never changes which tab you're in. Back/forward may.**

A tab is a full router experience. Change the URL and the active tab changes with it. Nothing focuses
another tab behind your back.

## Implementation Decisions

### Tab scope
Tabs are window-global. A tab may hold any route: a space, a canvas, a task, `/inbox`, `/loops`,
`/settings/$category`. The rail stays a global column; the sidebar beside it is a function of the
active tab, because the sidebar is derived from the route (`railPaneForMatches` → `railPaneHasSidebar`)
and the route is now per tab.

### The tab record is href-primary
`browser_tabs` stores an `href`, not a reference set. The existing identity columns
(`dashboardId` / `taskId` / `channelId` / `channelSection` / `appView`) demote to a label and icon cache.

References cannot express a location. They drop search params, and they have no representation at all
for most of the flattened route tree (`/`, `/activity`, `/loops`, `/loops/$loopId`, `/new`,
`/archived`, `/feeds/$feedId`, `/folders/$folderId`, `/tasks/pending/$key`, `/settings/$category`,
`/spaces`, and the space children `canvases`, `loops`, `new`, `context`). That is not only data loss:
`useAppView` collapses anything it does not recognise into `task-input`, and the strip then reconciles
the location against the wrong tab and navigates back off the page, which is what the warning at the
top of `BrowserTabStrip` is about. `/activity` and `/loops` are rail destinations, so this fires on
day one.

`rewriteSavedLocation` gains a second call site over persisted tab hrefs. The `/website/*` → `/spaces/*`
flatten already landed, so a snapshot written before it restores onto dead routes.

### No dedup, no teleporting
The identity dedup branch in `decideTabNavigation` is deleted. Navigating to something another tab
already shows replaces the active tab's target; it does not focus the other tab. Two tabs may hold the
same page, as in any browser.

That branch was load-bearing for one recovery case: a rapid tab switch whose history stamp was lost
still re-identified the intended tab from the route. Removing it means the stamp has to be reliable
rather than recoverable, so the `tabId` stamp is minted synchronously at the call site of every switch
(`applyLocalTransform` already runs in the same tick) and `serverActiveTabId` becomes persistence-only.
There is no route-based recovery fallback because a route cannot identify which of several
same-location tabs the user selected.

### Back / forward
Unchanged: one shared, tab-tagged timeline per window. Switching tabs pushes an entry, back at a tab
boundary returns to the previous tab. This is the one place the app is deliberately not browser-like,
and it is the only remaining path that moves you between tabs.

### Per-tab nav state
Most of "each tab has its own nav" is free, because the route is per tab. What is not in the URL:

- `channelPaneStore.pane` (`list` vs `channel`)
- `currentChannelStore.currentChannelId`, for routes with no `$channelId`
- the `keepListForChannelId` latch
- rail memory (below)

These live in **router history state** (primary, via module augmentation, the way `tabId` already does)
and are **written through to the tab row** for relaunch. History-primary because the state is per entry,
not per tab: open the list, enter a space, open the list again, press back, and a single per-tab value
lies. It also keeps the fast path fast, since history flips on navigate while the server snapshot
round-trips.

Toggling the list without navigating is a pure store write today. It gains a `router.replace` to stamp
the current entry.

### Rail memory, per tab
`railHistoryStore` does not die, it narrows. Each tab remembers where each rail destination was
*within that tab*, so clicking Inbox navigates the active tab to that tab's last inbox href rather than
to `/inbox`. No cross-tab movement, no dedup, no teleport. `RailVisit` is already `{href, spaces:{listOpen, spaceId}}`,
which is the per-tab `viewState` record being added anyway, so `lastByPane` moves into it unchanged.
A window-global memory would let tab 1's rail click restore an href tab 2 established, which is
cross-tab state bleed in another costume.

### Search moves to the rail
`CommandSearchBar` gives the title bar's middle back to the strip and becomes an icon at the top of
`NavRail`. The label and the `⌘K` hint move into the rail's existing `NavIcon` tooltip.

This is a shrink in affordance, and that file's own comment argues against it ("a target you aim at,
not an icon you hunt for"). It wins anyway because the bar is not an omnibox: it renders no URL,
accepts no typing, and its only job is to open the command menu. Browser-address-bar reasoning, and
the permanent second row it would justify, does not apply. The rail also survives `⌘B`, which the
sidebar does not.

### `+` opens `/spaces`
Blank tabs stop existing. A tab with no href cannot be a router location, and the blank state props up
four special cases: `activeTabIsBlank`, `primaryWindowHasNoTabs`, the `showBlankTab` override of the
`<Outlet>`, and the `activeIsBlank` guard inside `decideTabNavigation`. It is also the sole reason
`/spaces` must never redirect.

`+` navigates to `/spaces`, whose index renders the space grid. That page is currently unreachable:
`showSpaces()` navigates to the scoped channel whenever one exists, and `ChannelRouteSync` auto-scopes
to `#me` on cold start, so `navigateToSpaces()` is effectively dead code. The new-tab page becomes
"pick a space", which is the right browser analogy.

Cmd/Ctrl-clicking a rail destination is the other explicit new-tab action. It opens the destination's
root in a fresh tab and never runs the active tab's normal rail-navigation or remembered-visit path.

`BlankTabView` is deleted.

### Settings becomes a normal tab
The `isSettingsRoute` early return in `__root.tsx` renders no title bar, rail or sidebar. Under
tabs-everywhere that is a trapdoor: opening settings in a tab makes the whole strip vanish with no way
back but browser-back. Settings renders inside the content pane like any other route.

Two consequences: the settings panel has to work at content-pane width rather than window width, and
settings routes live outside `_shell`, so they will pick up `ContentHeader` on top of whatever header
the panel already draws.

Removing the early return also removes one of the two `TabShortcutFallback` mounts; the strip becomes
the only `⌘W` owner.

### Launch authority
The tabs snapshot decides where the app opens. `startupLocation` demotes to the fallback for the cases
with no snapshot: fresh install, flag off, and hosts with no tabs backend. It cannot be deleted, since
it carries first-run provisioning (`#general`, `firstRun.generalChannelId`) and the legacy-key migration,
none of which is about tabs.

This costs an ordering change. `App.tsx` resolves `startupLocation` and calls `router.history.replace`
**before the router mounts**, gating the loading screen on it, while the snapshot is seeded later by a
boot contribution. The snapshot has to move into that boot gate. Optimistically painting the saved href
and reconciling afterwards was considered and rejected: it flashes when the two disagree, and after a
normal quit they never disagree, because both are written from the same navigations.

`rememberStartupLocation`'s subscription on every history change should write only when the strip is
off. Left on, it is a second, per-window record of where you were, which is the duplicate authority
this work removes everywhere else.

### View state tiers
Every view store is assigned a tier. The rule: **if it describes the content a tab is showing, it is
per tab; if it describes how the app is configured, it is global.**

| Tier | Restores on | Lives in | Stores |
| --- | --- | --- | --- |
| 1, per history entry | back/forward and tab switch | history state, written through to the tab row | route href, `channelPaneStore.pane`, `currentChannelStore.currentChannelId`, rail memory |
| 2, per tab | tab switch | tab row `viewState` | `threadPanelStore`, `canvasChatPanelStore`, `dashboardEditStore`, `taskFeedSelectionStore`, `rightPanelStore` open/which |
| 3, global | never, it is not navigation | localStorage, as today | `channelsSidebarStore.width`, `rightPanelStore` width, `sidebarStore` nav order and overrides, `spaceTreeStore` expansion, `pinnedTabsStore`, `sidebarPeekStore` |

`rightPanelStore` splits because which panel is open is content while its width is a preference, and a
user who resizes it in one tab expects that width everywhere.

Tier 2 is implemented with one `createTabScopedStore` primitive that keys existing state by tab id and
reads the active tab, rather than five bespoke rewrites. New stores then get a one-line decision instead
of an accidental default.

Judgement calls worth revisiting once it is usable, all cheap to flip once the primitive exists:
`dashboardEditStore` is per tab (two tabs both believing they are the editor of one canvas is a
data-loss shape); `activityFilterStore` is global (a filter reads as a preference);
`spaceTreeStore` expansion is global (tree expansion is muscle memory, not location).

### Gating
A new `SPACES_TABS` flag gates only whether the strip **renders** under `channelsLayout`. Everything
above is unconditional.

Flag-off is the degenerate case of the same implementation, not a second one: with a single tab, the
tab is the window, so per-tab history, per-tab `viewState` and per-tab rail memory all behave exactly
as the window-global versions do today. Gating the model instead would fork the subsystem being
rewritten and double its test surface.

## Shape

1. **Model, nothing visible.** href-primary schema and migration, per-tab `viewState`, rail memory
   moved onto the tab, dedup deleted, snapshot in the boot gate. One implicit tab throughout.
2. **The UX, one PR.** Strip renders under `channelsLayout` behind `SPACES_TABS`, search moves to the
   rail, settings becomes a tab, `+` goes to `/spaces`, tier-2 stores get scoped.

## What This Deletes

`railHistoryStore` as a global, `restoreVisit`, the identity dedup branch, `activeTabIsBlank`,
`primaryWindowHasNoTabs`, `showBlankTab`, `BlankTabView`, the `activeIsBlank` guard, the
"`/spaces` must not redirect" constraint, the settings early return, and one `TabShortcutFallback` mount.
`decideTabNavigation` shrinks to roughly "stamp the entry, or activate on a history tag".

## Open Questions

- **`⌘W` on the last tab.** A browser closes the window; the primary window currently lands on the
  channels landing instead.
- **Strip overflow.** Already a rough edge (pinned pills are incompressible, the tablist only clips).
  Rail destinations becoming tabs makes it likely on day one rather than eventually.
- **Bluebird flag-off restore.** A flag-off user with several `/spaces/*` tabs is bounced once per
  focus by the guard in `__root.tsx`, which only sees the active tab. Either filter bluebird-only hrefs
  at restore, or skip the snapshot entirely while the flag is off.

## Note

`packages/ui/src/features/browser-tabs/AGENTS.md` still describes shipped behaviour and should not be
edited until this is built. When it is, the invariant at the top of this document belongs there.
