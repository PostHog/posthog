import type {
  BrowserTab,
  TabsSnapshot,
  TabViewState,
} from "./browser-tabs-schemas";

/** Spacing between adjacent tab positions, leaving room to insert without reindex. */
export const POSITION_GAP = 1000;

type Clock = () => number;
type IdFactory = () => string;

export type OpenTabResult = {
  snapshot: TabsSnapshot;
  tabId: string;
};

export type CloseTabResult = {
  snapshot: TabsSnapshot;
  /** Tab focused after the close, or null for the channels landing. */
  nextActiveTabId: string | null;
  /** Set when closing the last tab of a secondary window should close it. */
  closedWindowId: string | null;
};

function tabsInWindow(snapshot: TabsSnapshot, windowId: string): BrowserTab[] {
  return snapshot.tabs
    .filter((t) => t.windowId === windowId)
    .sort((a, b) => a.position - b.position);
}

/** The primary window, falling back to the first one (web has a single window). */
export function primaryWindow(snapshot: TabsSnapshot) {
  return snapshot.windows.find((w) => w.isPrimary) ?? snapshot.windows[0];
}

function setActiveTab(
  snapshot: TabsSnapshot,
  windowId: string,
  tabId: string | null,
): TabsSnapshot {
  return {
    ...snapshot,
    windows: snapshot.windows.map((w) =>
      w.id === windowId ? { ...w, activeTabId: tabId } : w,
    ),
  };
}

/**
 * Focus a tab in a window, validating the target: the tab must exist and live
 * in that window, otherwise the snapshot is returned unchanged. A `null` tabId
 * clears focus (the landing state). This is the persistence-safe primitive —
 * history entries can carry ids of tabs closed since (back/forward replay), and
 * blindly persisting such an id leaves the window with a dangling activeTabId,
 * after which every navigation looks like "no active tab" and opens a new tab.
 */
export function setWindowActiveTab(
  snapshot: TabsSnapshot,
  windowId: string,
  tabId: string | null,
): TabsSnapshot {
  if (tabId !== null) {
    const tab = snapshot.tabs.find((t) => t.id === tabId);
    if (!tab || tab.windowId !== windowId) return snapshot;
  }
  const window = snapshot.windows.find((w) => w.id === windowId);
  if (!window || window.activeTabId === tabId) return snapshot;
  return setActiveTab(snapshot, windowId, tabId);
}

/** What a tab points at: a canvas, a task, or neither. */
export type TabTarget = {
  dashboardId: string | null;
  taskId: string | null;
};

/**
 * Where a tab is. `href` is the truth — it is the only field that survives a
 * route outside the reference vocabulary below, and the only one that keeps
 * search params. `viewState` carries the nav state the href cannot express.
 */
export type TabLocation = {
  href: string | null;
  viewState: TabViewState | null;
};

/**
 * Route-derived label and icon metadata stored alongside a tab's location.
 * This cache is compared only to decide whether the active tab record needs an
 * update. It never establishes equivalence between different tabs.
 */
export type TabIdentity = {
  dashboardId: string | null;
  taskId: string | null;
  channelId: string | null;
  channelSection: string | null;
  appView: string | null;
};

function sameIdentity(a: TabIdentity, b: TabIdentity): boolean {
  return (
    a.dashboardId === b.dashboardId &&
    a.taskId === b.taskId &&
    a.channelId === b.channelId &&
    a.channelSection === b.channelSection &&
    a.appView === b.appView
  );
}

/**
 * Whether two view states describe the same visit. Compared structurally so a
 * change with no navigation — toggling the space list, a rail destination
 * recording where it was — still reaches the tab record.
 */
function sameViewState(
  a: TabViewState | null,
  b: TabViewState | null,
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Open a location in a new tab and focus it.
 *
 * No dedup: navigating to something another tab already shows must never move
 * you to that tab (see {@link decideTabNavigation}), and an explicit open makes
 * the same promise. Two tabs may hold the same page, as in any browser.
 */
export function openTab(
  snapshot: TabsSnapshot,
  input: TabTarget &
    TabLocation & {
      windowId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
      makeId: IdFactory;
      now: Clock;
    },
): OpenTabResult {
  const { windowId, makeId, now } = input;
  const siblings = tabsInWindow(snapshot, windowId);
  const lastPos = siblings.length ? siblings[siblings.length - 1].position : 0;
  const ts = now();
  const tab: BrowserTab = {
    id: makeId(),
    windowId,
    href: input.href,
    viewState: input.viewState,
    dashboardId: input.dashboardId,
    taskId: input.taskId,
    channelId: input.channelId,
    channelSection: input.channelSection ?? null,
    appView: input.appView ?? null,
    position: lastPos + POSITION_GAP,
    scrollState: null,
    createdAt: ts,
    lastActiveAt: ts,
  };
  const withTab: TabsSnapshot = { ...snapshot, tabs: [...snapshot.tabs, tab] };
  return {
    snapshot: setActiveTab(withTab, windowId, tab.id),
    tabId: tab.id,
  };
}

/**
 * Remove every persisted location and replace it with one fresh tab per window.
 * Window identities stay stable so live renderer windows remain attached, while
 * all route, title, and view-state metadata from the previous scope disappears.
 */
export function resetTabs(
  snapshot: TabsSnapshot,
  input: { href: string; makeId: IdFactory; now: Clock },
): TabsSnapshot {
  let reset: TabsSnapshot = {
    windows: snapshot.windows.map((window) => ({
      ...window,
      activeTabId: null,
    })),
    tabs: [],
  };

  for (const window of reset.windows) {
    reset = openTab(reset, {
      windowId: window.id,
      href: input.href,
      viewState: null,
      dashboardId: null,
      taskId: null,
      channelId: null,
      makeId: input.makeId,
      now: input.now,
    }).snapshot;
  }

  return reset;
}

/**
 * Point an existing tab at a location: the in-tab navigation primitive. Used
 * when the user navigates while a tab is active, so the location replaces the
 * tab's contents instead of opening a new tab. Focuses it unless the caller is
 * completing work in a background tab.
 */
export function setTabTarget(
  snapshot: TabsSnapshot,
  input: TabTarget &
    TabLocation & {
      tabId: string;
      channelId: string | null;
      channelSection?: string | null;
      appView?: string | null;
      /** Keep the current tab focused when an async operation finishes in the
       * background. Normal in-tab navigation activates by default. */
      activate?: boolean;
      now: Clock;
    },
): TabsSnapshot {
  const tab = snapshot.tabs.find((t) => t.id === input.tabId);
  if (!tab) return snapshot;
  const ts = input.now();
  const withTarget: TabsSnapshot = {
    ...snapshot,
    tabs: snapshot.tabs.map((t) =>
      t.id === input.tabId
        ? {
            ...t,
            href: input.href,
            viewState: input.viewState,
            dashboardId: input.dashboardId,
            taskId: input.taskId,
            channelId: input.channelId,
            channelSection: input.channelSection ?? null,
            appView: input.appView ?? null,
            lastActiveAt: input.activate === false ? t.lastActiveAt : ts,
          }
        : t,
    ),
  };
  return input.activate === false
    ? withTarget
    : setActiveTab(withTarget, tab.windowId, input.tabId);
}

/**
 * Close a tab. Focus moves to the nearest sibling. Closing the last tab of a
 * secondary window signals that the window should close; closing the last tab
 * of the primary window leaves it on the channels landing (activeTabId null).
 */
export function closeTab(
  snapshot: TabsSnapshot,
  tabId: string,
): CloseTabResult {
  const tab = snapshot.tabs.find((t) => t.id === tabId);
  if (!tab) {
    return { snapshot, nextActiveTabId: null, closedWindowId: null };
  }
  const window = snapshot.windows.find((w) => w.id === tab.windowId);
  const siblings = tabsInWindow(snapshot, tab.windowId);
  const idx = siblings.findIndex((t) => t.id === tabId);
  const remaining = siblings.filter((t) => t.id !== tabId);

  const removedTabs = snapshot.tabs.filter((t) => t.id !== tabId);

  if (remaining.length === 0) {
    if (window && !window.isPrimary) {
      // Drop the window too.
      return {
        snapshot: {
          windows: snapshot.windows.filter((w) => w.id !== tab.windowId),
          tabs: removedTabs,
        },
        nextActiveTabId: null,
        closedWindowId: tab.windowId,
      };
    }
    // Primary window → channels landing.
    return {
      snapshot: setActiveTab(
        { ...snapshot, tabs: removedTabs },
        tab.windowId,
        null,
      ),
      nextActiveTabId: null,
      closedWindowId: null,
    };
  }

  // Focus the tab that took the closed slot, else the new last one.
  const next = remaining[Math.min(idx, remaining.length - 1)];
  const wasActive = window?.activeTabId === tabId;
  const base: TabsSnapshot = { ...snapshot, tabs: removedTabs };
  return {
    snapshot: wasActive ? setActiveTab(base, tab.windowId, next.id) : base,
    nextActiveTabId: wasActive ? next.id : (window?.activeTabId ?? null),
    closedWindowId: null,
  };
}

/**
 * Close several tabs at once — the bulk primitive behind "close other tabs" /
 * "close tabs to the right/left". Composes {@link closeTab} so the per-window
 * succession rules (survivor focus, secondary-window drop, primary lands on
 * channels) live in exactly one place.
 *
 * `focusTabId` is the bulk close's anchor (the right-clicked tab, which always
 * survives these operations). When a window's active tab is among those closed,
 * focus moves to the anchor rather than closeTab's stored-order neighbour — the
 * caller closes by *displayed* (pinned-first) order, so the stored-order
 * neighbour can be a pinned tab at the far end of the strip.
 */
export function closeTabs(
  snapshot: TabsSnapshot,
  tabIds: string[],
  focusTabId?: string | null,
): TabsSnapshot {
  const ids = new Set(tabIds);
  if (ids.size === 0) return snapshot;

  // Windows whose active tab is being closed — only these honour the anchor.
  const activeClosedWindows = new Set(
    snapshot.windows
      .filter((w) => w.activeTabId != null && ids.has(w.activeTabId))
      .map((w) => w.id),
  );

  let next = snapshot;
  for (const id of ids) {
    next = closeTab(next, id).snapshot;
  }

  if (focusTabId) {
    const anchor = next.tabs.find((t) => t.id === focusTabId);
    if (anchor && activeClosedWindows.has(anchor.windowId)) {
      next = setActiveTab(next, anchor.windowId, focusTabId);
    }
  }
  return next;
}

/**
 * Persist a window's full tab order — the drop primitive for drag-to-reorder.
 * The UI sends the final stored order (pin-agnostic; the pinned-first display
 * partition is applied on top at render time) and it becomes the stored order.
 * Ids not in the window are ignored; the window's tabs missing from the list
 * keep their relative order after the listed ones. Tabs whose position does not
 * change keep their object identity so downstream memos/effects stay stable.
 */
export function setTabOrder(
  snapshot: TabsSnapshot,
  windowId: string,
  orderedTabIds: string[],
): TabsSnapshot {
  const current = tabsInWindow(snapshot, windowId);
  const byId = new Map(current.map((t) => [t.id, t]));
  const listed = orderedTabIds
    .map((id) => byId.get(id))
    .filter((t): t is BrowserTab => t !== undefined);
  const listedIds = new Set(listed.map((t) => t.id));
  const rest = current.filter((t) => !listedIds.has(t.id));
  const positioned = new Map<string, number>(
    [...listed, ...rest].map((t, i) => [t.id, (i + 1) * POSITION_GAP]),
  );
  let changed = false;
  const tabs = snapshot.tabs.map((t) => {
    const pos = positioned.get(t.id);
    if (pos === undefined || pos === t.position) return t;
    changed = true;
    return { ...t, position: pos };
  });
  return changed ? { ...snapshot, tabs } : snapshot;
}

// ----- Navigation intent (drives the renderer effect) -----

/**
 * What a navigation means for the tab strip, given the router state. This is the
 * decision the renderer makes on every location change; extracted as a pure
 * function so the UX rules are testable without a router.
 *
 * The governing rule: **navigation never changes which tab you are in;
 * back/forward may.** So there is exactly one branch that moves focus between
 * tabs (`activate`, driven by a history tag), and it is unreachable from a
 * plain navigation.
 *
 * - `activate`: the entry is tagged with a different live tab (a tab switch, or
 *   a back/forward replay landing on that tab) → focus it.
 * - `replace`: a navigation while a tab is active → point that tab at the new
 *   location in place, and stamp the entry.
 * - `open`: a navigation with no active tab → open one.
 * - `stamp`: the active tab already holds this location → just tag the entry so
 *   back/forward can replay it.
 * - `noop`: nothing to do.
 */
export type TabNavDecision =
  | { type: "activate"; tabId: string }
  | ({
      type: "replace";
      tabId: string;
      stampTabId: string | null;
    } & TabLocation &
      TabIdentity)
  | ({
      type: "open";
      stampTabId: string | null;
    } & TabLocation &
      TabIdentity)
  | { type: "stamp"; stampTabId: string }
  | { type: "noop" };

export function decideTabNavigation(input: {
  /** tabId carried in the current history entry, if any. */
  historyTabId: string | null;
  /**
   * Ids of the tabs that currently exist in this window. A history entry can
   * be tagged with a tab that has since been closed (back/forward replays the
   * entry); such a dead tag must NOT activate — it falls through and the route
   * decides, which also re-stamps the entry with a live tab.
   */
  windowTabIds?: readonly string[];
  /** The window's active tab id from the server snapshot (lags history). */
  serverActiveTabId: string | null;
  /** The active tab record, if one exists. */
  activeTab: {
    id: string;
    href: string | null;
    viewState: TabViewState | null;
    identity: TabIdentity;
  } | null;
  /** The location being navigated to. */
  href: string;
  /** Nav state this location carries that the href cannot express. */
  viewState: TabViewState | null;
  /** Route-derived label/icon cache written alongside the location. */
  identity: TabIdentity;
}): TabNavDecision {
  const { historyTabId, serverActiveTabId, activeTab, href, identity } = input;
  const viewState = input.viewState;

  // Tagged entry for a DIFFERENT tab → a tab switch or a back/forward replay.
  // Focus it (this is how "back returns to the previous tab" resolves). Two
  // guards: (1) the tagged tab must still exist — back/forward can replay an
  // entry whose tab was closed, and activating a dead id persists a dangling
  // activeTabId (every nav then opens a new tab); (2) when the tag equals the
  // active tab we must NOT stop here: an in-tab nav can arrive tagged with the
  // active tab — fall through and decide from the route.
  const historyTabIsLive =
    !!historyTabId &&
    (input.windowTabIds ? input.windowTabIds.includes(historyTabId) : true);
  if (historyTabId && historyTabIsLive && historyTabId !== serverActiveTabId) {
    return { type: "activate", tabId: historyTabId };
  }

  // Everything below is a plain navigation, and it stays in the current tab.
  //
  // `href` is the primary key. Identity is a label cache, all-null for every
  // route outside its vocabulary, so `/loops` and `/archived` are equal through
  // it; deciding on identity made such navigations look like "already there"
  // and the strip never followed them.
  //
  // The three are OR'd, so identity can only ever ADD a write, never suppress
  // one. It has to be here: the router updates `location.href` before the new
  // route's params, so the first pass writes the new href with the OLD
  // identity. Keyed on href alone, the corrected identity arriving a frame
  // later compares equal and is dropped, and the tab keeps a stale label for
  // good (a task tab that renders as its space).
  if (!activeTab) {
    return { type: "open", href, viewState, ...identity, stampTabId: null };
  }
  if (
    activeTab.href !== href ||
    !sameViewState(activeTab.viewState, viewState) ||
    !sameIdentity(activeTab.identity, identity)
  ) {
    return {
      type: "replace",
      tabId: activeTab.id,
      href,
      viewState,
      ...identity,
      stampTabId: serverActiveTabId,
    };
  }
  return serverActiveTabId
    ? { type: "stamp", stampTabId: serverActiveTabId }
    : { type: "noop" };
}
