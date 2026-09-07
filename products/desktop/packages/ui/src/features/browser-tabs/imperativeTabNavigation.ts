import {
  type BrowserTab,
  primaryWindow,
  setTabTarget as setTabTargetLocal,
  type TabIdentity,
} from "@posthog/shared";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { pushTabHistoryEntry } from "./tabHistory";
import { applyLocalTransform, persistTabTarget, readMirror } from "./tabsSync";

export interface BrowserTabDestination extends Partial<TabIdentity> {
  href: string;
  title?: string;
}

export type BrowserTabNavigationResult = "active" | "background" | "closed";

/** The tab attached to the current history entry, or null when tabs are off. */
export function getCurrentBrowserTabId(): string | null {
  return getRouterOrNull()?.history.location.state.tabId ?? null;
}

/**
 * Whether the tab still exists in the mirror. A null tabId means tabs are off,
 * so there is one window whose composer cannot have been closed with the tab.
 */
export function isBrowserTabOpen(tabId: string | null): boolean {
  if (!tabId) return true;
  return readMirror().tabs.some((candidate) => candidate.id === tabId);
}

/**
 * Whether a tab shows this destination, compared on the href (the tab's source
 * of truth) with the reference-vocabulary fields as fallback for tabs
 * persisted before hrefs were stored.
 */
function tabShowsDestination(
  tab: BrowserTab,
  dest: BrowserTabDestination,
): boolean {
  if (tab.href === dest.href) return true;
  if (tab.href !== null) return false;
  if (dest.taskId !== undefined) return tab.taskId === (dest.taskId ?? null);
  if (dest.dashboardId !== undefined) {
    return tab.dashboardId === (dest.dashboardId ?? null);
  }
  return false;
}

/**
 * Focus an existing tab that shows this destination, instead of opening a
 * duplicate. Selection goes through pushTabHistoryEntry, the same path a tab
 * click uses, so the navigation effect sees a tagged entry and settles the
 * switch (durable focus, view-state restore). Returns false when no tab
 * matches, or when the matching tab is already the active one.
 */
export function focusExistingTab(destination: BrowserTabDestination): boolean {
  const window = primaryWindow(readMirror());
  if (!window) return false;
  const tab = readMirror().tabs.find(
    (candidate) =>
      candidate.windowId === window.id &&
      tabShowsDestination(candidate, destination),
  );
  if (!tab) return false;
  if (tab.id === getRouterOrNull()?.history.location.state.tabId) return true;

  const history = getRouterOrNull()?.history;
  if (!history) return false;
  pushTabHistoryEntry(history, tab.href ?? destination.href, tab.id);
  return true;
}

/**
 * Move one browser tab to a new route without stealing focus from another tab.
 * Active tabs use router history; background tabs update their durable target
 * and will load that route when the user returns.
 */
export function navigateBrowserTab(
  tabId: string | null,
  destination: BrowserTabDestination,
  navigateActiveTab: () => void,
): BrowserTabNavigationResult {
  if (!tabId) {
    navigateActiveTab();
    return "active";
  }

  const router = getRouterOrNull();
  if (router?.history.location.state.tabId === tabId) {
    navigateActiveTab();
    return "active";
  }

  const tab = readMirror().tabs.find((candidate) => candidate.id === tabId);
  if (!tab) return "closed";

  const target = {
    tabId,
    href: destination.href,
    viewState: {
      ...(tab.viewState ?? {}),
      ...(destination.title ? { title: destination.title } : {}),
    },
    dashboardId: destination.dashboardId ?? null,
    taskId: destination.taskId ?? null,
    channelId: destination.channelId ?? null,
    channelSection: destination.channelSection ?? null,
    appView: destination.appView ?? null,
    activate: false,
  };

  applyLocalTransform((snapshot) =>
    setTabTargetLocal(snapshot, { ...target, now: Date.now }),
  );
  persistTabTarget(target);
  return "background";
}
