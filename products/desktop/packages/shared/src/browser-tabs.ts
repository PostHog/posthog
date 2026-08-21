import type { BrowserTab, TabsSnapshot } from "./browser-tabs-schemas";

/** Spacing between adjacent tab positions, leaving room to insert without reindex. */
export const POSITION_GAP = 1000;

type Clock = () => number;
type IdFactory = () => string;

export type OpenTabResult = {
  snapshot: TabsSnapshot;
  tabId: string;
  /** False when an existing tab was focused (dedup) rather than created. */
  opened: boolean;
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

/**
 * True when the primary window's active tab is a blank "+" tab: no canvas,
 * task, or channel. The blank tab parks at the channels index (`/website`),
 * whose route would otherwise redirect to the first channel — callers use this
 * to suppress that redirect so the blank tab (and the in-flight navigation
 * leaving it) isn't hijacked to `channels[0]`.
 */
export function activeTabIsBlank(snapshot: TabsSnapshot): boolean {
  const w = primaryWindow(snapshot);
  if (!w?.activeTabId) return false;
  const t = snapshot.tabs.find((x) => x.id === w.activeTabId);
  return (
    !!t &&
    t.dashboardId == null &&
    t.taskId == null &&
    t.channelId == null &&
    t.appView == null
  );
}

/**
 * True when the primary window has no tabs at all — the user closed every tab.
 * The channels index renders the new-tab screen for this state rather than
 * redirecting to the first channel, which would silently re-open a tab.
 */
export function primaryWindowHasNoTabs(snapshot: TabsSnapshot): boolean {
  const w = primaryWindow(snapshot);
  if (!w) return false;
  return !snapshot.tabs.some((t) => t.windowId === w.id);
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

/** What a tab points at: a canvas, a task, or neither (blank). */
export type TabTarget = {
  dashboardId: string | null;
  taskId: string | null;
};

/**
 * Everything that identifies a tab's contents: a canvas, a task, or a channel
 * sub-section (channel + section). Two tabs with the same identity are the same
 * page, so dedup and in-tab-nav comparisons key on all four — a channel's
 * `history` and `artifacts`, or two channels' artifacts, are distinct pages.
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
 * Open a target (canvas or task) in a window, deduping within that window: if a
 * tab for the same target already exists in the window it is focused, otherwise
 * a new tab is appended. Duplicates across different windows are allowed.
 */
export function openOrFocusTab(
  snapshot: TabsSnapshot,
  input: TabTarget & {
    windowId: string;
    channelId: string | null;
    channelSection?: string | null;
    appView?: string | null;
    makeId: IdFactory;
    now: Clock;
  },
): OpenTabResult {
  const { windowId, dashboardId, taskId, channelId, makeId, now } = input;
  const channelSection = input.channelSection ?? null;
  const appView = input.appView ?? null;
  const existing = snapshot.tabs.find(
    (t) =>
      t.windowId === windowId &&
      sameIdentity(t, {
        dashboardId,
        taskId,
        channelId,
        channelSection,
        appView,
      }),
  );
  if (existing) {
    const ts = now();
    const withActivity: TabsSnapshot = {
      ...snapshot,
      tabs: snapshot.tabs.map((t) =>
        t.id === existing.id ? { ...t, lastActiveAt: ts } : t,
      ),
    };
    return {
      snapshot: setActiveTab(withActivity, windowId, existing.id),
      tabId: existing.id,
      opened: false,
    };
  }

  return appendTab(snapshot, {
    windowId,
    dashboardId,
    taskId,
    channelId,
    channelSection,
    appView,
    makeId,
    now,
  });
}

function appendTab(
  snapshot: TabsSnapshot,
  input: TabTarget & {
    windowId: string;
    channelId: string | null;
    channelSection?: string | null;
    appView?: string | null;
    makeId: IdFactory;
    now: Clock;
  },
): OpenTabResult {
  const { windowId, dashboardId, taskId, channelId, makeId, now } = input;
  const siblings = tabsInWindow(snapshot, windowId);
  const lastPos = siblings.length ? siblings[siblings.length - 1].position : 0;
  const ts = now();
  const tab: BrowserTab = {
    id: makeId(),
    windowId,
    dashboardId,
    taskId,
    channelId,
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
    opened: true,
  };
}

/**
 * Append a blank tab (no target) and focus it. The strip shows it as an empty
 * placeholder; navigating while it is active replaces its contents via
 * {@link setTabTarget}.
 */
export function newBlankTab(
  snapshot: TabsSnapshot,
  input: { windowId: string; makeId: IdFactory; now: Clock },
): OpenTabResult {
  return appendTab(snapshot, {
    windowId: input.windowId,
    dashboardId: null,
    taskId: null,
    channelId: null,
    makeId: input.makeId,
    now: input.now,
  });
}

/**
 * Point an existing tab at a target (canvas or task) — the in-tab navigation
 * primitive. Used when the user navigates while a tab is active, so the target
 * replaces the tab's contents instead of opening a new tab. Also focuses it.
 */
export function setTabTarget(
  snapshot: TabsSnapshot,
  input: TabTarget & {
    tabId: string;
    channelId: string | null;
    channelSection?: string | null;
    appView?: string | null;
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
            dashboardId: input.dashboardId,
            taskId: input.taskId,
            channelId: input.channelId,
            channelSection: input.channelSection ?? null,
            appView: input.appView ?? null,
            lastActiveAt: ts,
          }
        : t,
    ),
  };
  return setActiveTab(withTarget, tab.windowId, input.tabId);
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
 * - `activate`: the entry is tagged with a tab (a tab switch, or a back/forward
 *   replay landing on a tab) → focus that tab.
 * - `replace`: an untagged navigation to a target (canvas or task) while a tab
 *   is active → swap the active tab's target in place (in-tab navigation), and
 *   stamp the entry.
 * - `open`: an untagged navigation to a target with no active tab → open one.
 * - `stamp`: an untagged navigation whose target already matches the active tab
 *   → nothing to change, just tag the entry so back/forward can replay it.
 * - `noop`: nothing to do (already on the right tab, or a blank/landing route).
 */
export type TabNavDecision =
  | { type: "activate"; tabId: string }
  | {
      type: "replace";
      tabId: string;
      dashboardId: string | null;
      taskId: string | null;
      channelId: string | null;
      channelSection: string | null;
      appView: string | null;
      stampTabId: string | null;
    }
  | {
      type: "open";
      dashboardId: string | null;
      taskId: string | null;
      channelId: string | null;
      channelSection: string | null;
      appView: string | null;
      stampTabId: string | null;
    }
  | { type: "stamp"; stampTabId: string }
  | { type: "noop" };

export function decideTabNavigation(input: {
  /** tabId carried in the current history entry, if any. */
  historyTabId: string | null;
  /**
   * Ids of the tabs that currently exist in this window. A history entry can
   * be tagged with a tab that has since been closed (back/forward replays the
   * entry); such a dead tag must NOT activate — it falls through and the route
   * decides (in-tab replace / open / stamp), which also re-stamps the entry
   * with a live tab. When omitted, tags are trusted (legacy behaviour).
   */
  windowTabIds?: readonly string[];
  /**
   * The window's tabs with their identities. When a navigation's route matches
   * an existing tab that isn't the active one, we activate that tab instead of
   * replacing the active tab's target (which would duplicate it) or opening a
   * second copy. This also self-heals a rapid tab switch whose history stamp
   * was lost: it arrives looking like an in-tab nav, but the route still
   * identifies the intended tab, so we focus it rather than corrupt the active
   * tab. When omitted, this dedup is skipped (legacy behaviour).
   */
  windowTabs?: readonly (TabIdentity & { id: string })[];
  /** The window's active tab id from the server snapshot (lags history). */
  serverActiveTabId: string | null;
  /** The active tab record, if one exists. */
  activeTab: {
    id: string;
    dashboardId: string | null;
    taskId: string | null;
    channelId?: string | null;
    channelSection?: string | null;
    appView?: string | null;
  } | null;
  /** Canvas in the current route, if any. */
  routeDashboardId: string | null;
  /** Task in the current route, if any. */
  routeTaskId: string | null;
  routeChannelId: string | null;
  /** Channel sub-section in the current route, if any. */
  routeChannelSection?: string | null;
  /** Top-level app page in the current route, if any. */
  routeAppView?: string | null;
}): TabNavDecision {
  const {
    historyTabId,
    serverActiveTabId,
    activeTab,
    routeDashboardId,
    routeTaskId,
    routeChannelId,
  } = input;
  const routeChannelSection = input.routeChannelSection ?? null;
  const routeAppView = input.routeAppView ?? null;

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

  // Navigation within the active tab. A real target is a canvas, a task, or a
  // channel (home or sub-section); the landing/blank route (no channel) is a
  // noop.
  const routeIdentity: TabIdentity = {
    dashboardId: routeDashboardId,
    taskId: routeTaskId,
    channelId: routeChannelId,
    channelSection: routeChannelSection,
    appView: routeAppView,
  };
  if (!routeDashboardId && !routeTaskId && !routeChannelId && !routeAppView) {
    return { type: "noop" };
  }

  const activeMatchesRoute =
    !!activeTab &&
    sameIdentity(
      {
        dashboardId: activeTab.dashboardId,
        taskId: activeTab.taskId,
        channelId: activeTab.channelId ?? null,
        channelSection: activeTab.channelSection ?? null,
        appView: activeTab.appView ?? null,
      },
      routeIdentity,
    );

  // A blank active tab is a fresh `+` tab waiting for its first target: the
  // navigation is "fill me", never a switch — so the dedup below must not
  // steal it (activating another tab would strand the blank forever).
  const activeIsBlank =
    !!activeTab &&
    activeTab.dashboardId == null &&
    activeTab.taskId == null &&
    (activeTab.channelId ?? null) == null &&
    (activeTab.appView ?? null) == null;

  // The route already lives in another tab → focus it instead of replacing the
  // active tab's target (which would leave two tabs on the same identity) or
  // opening a duplicate. Also recovers a rapid switch whose history tag was
  // lost: the intended tab is still identified by the route. Only when the
  // active tab does NOT already show the route — otherwise, if a duplicate tab
  // already exists, we'd bounce between the two identical tabs forever.
  if (!activeMatchesRoute && !activeIsBlank) {
    const existingMatch = input.windowTabs?.find(
      (t) => t.id !== activeTab?.id && sameIdentity(t, routeIdentity),
    );
    if (existingMatch) {
      return { type: "activate", tabId: existingMatch.id };
    }
  }

  if (activeTab && !activeMatchesRoute) {
    return {
      type: "replace",
      tabId: activeTab.id,
      dashboardId: routeDashboardId,
      taskId: routeTaskId,
      channelId: routeChannelId,
      channelSection: routeChannelSection,
      appView: routeAppView,
      stampTabId: serverActiveTabId,
    };
  }
  if (!activeTab) {
    return {
      type: "open",
      dashboardId: routeDashboardId,
      taskId: routeTaskId,
      channelId: routeChannelId,
      channelSection: routeChannelSection,
      appView: routeAppView,
      stampTabId: serverActiveTabId,
    };
  }
  // Active tab already shows this target — just tag the entry.
  return serverActiveTabId
    ? { type: "stamp", stampTabId: serverActiveTabId }
    : { type: "noop" };
}
