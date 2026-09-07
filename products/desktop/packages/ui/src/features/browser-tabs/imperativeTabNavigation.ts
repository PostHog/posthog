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

function tabShowsDestination(
  tab: BrowserTab,
  dest: BrowserTabDestination,
): boolean {
  if (dest.taskId) return tab.taskId === dest.taskId;
  if (dest.dashboardId) return tab.dashboardId === dest.dashboardId;
  return tab.href === dest.href;
}

export function focusExistingTab(destination: BrowserTabDestination): boolean {
  const mirror = readMirror();
  const window = primaryWindow(mirror);
  const history = getRouterOrNull()?.history;
  if (!window || !history) return false;

  const matchesDestination = (candidate: BrowserTab) =>
    candidate.windowId === window.id &&
    tabShowsDestination(candidate, destination);

  // Tabs are not deduplicated, so several tabs can show one target. Keep the
  // active tab when it is one of them, instead of a switch to an older twin.
  const activeTabId = history.location.state.tabId;
  const activeTab = mirror.tabs.find(
    (candidate) => candidate.id === activeTabId,
  );
  if (activeTab && matchesDestination(activeTab)) return true;

  const tab = mirror.tabs.find(matchesDestination);
  if (!tab) return false;

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
