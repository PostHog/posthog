import {
  type BrowserTab,
  openTab as openTabLocal,
  primaryWindow,
  setTabTarget as setTabTargetLocal,
  type TabIdentity,
} from "@posthog/shared";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import type { BrowserTabsClient } from "./browserTabsClient";
import { pushTabHistoryEntry } from "./tabHistory";
import {
  applyLocalTransform,
  persistTabTarget,
  persistWrite,
  readMirror,
  reseedMirror,
} from "./tabsSync";

/**
 * Synchronous variant of {@link openInNewBrowserTab} for callers whose transient
 * state (a composer prefill) must land in the same tick as the navigation.
 * Opens only from the warm mirror; returns null when it hasn't seeded, and the
 * caller falls back to an in-tab navigation.
 */
export function openInNewBrowserTabSync(
  client: BrowserTabsClient,
  destination: BrowserTabDestination,
): string | null {
  const window = primaryWindow(readMirror());
  const history = getRouterOrNull()?.history;
  if (!window || !history) return null;
  const tabId = crypto.randomUUID();
  const input = {
    windowId: window.id,
    href: destination.href,
    viewState: destination.title ? { title: destination.title } : null,
    dashboardId: destination.dashboardId ?? null,
    taskId: destination.taskId ?? null,
    channelId: destination.channelId ?? null,
    channelSection: destination.channelSection ?? null,
    appView: destination.appView ?? null,
  };
  applyLocalTransform(
    (snapshot) =>
      openTabLocal(snapshot, { ...input, makeId: () => tabId, now: Date.now })
        .snapshot,
  );
  pushTabHistoryEntry(history, destination.href, tabId);
  void persistWrite(() => client.openTab({ ...input, tabId }));
  return tabId;
}

/**
 * Opens an inbound destination (a deep link, a notification click) in its own
 * tab, without disturbing the tab the user is on. Resolves to the new tab's id,
 * or null when browser tabs have no window to open into (the caller then falls
 * back to a plain navigation, so the link is never dropped).
 *
 * The write follows the strip's local-first contract: apply the shared
 * `openTab` transform to the mirror synchronously, push the tagged history
 * entry in the same tick, then persist in the background. The strip's
 * navigation effect sees the new history entry, treats its tag as a live tab
 * switch, and focuses it.
 */
export async function openInNewBrowserTab(
  client: BrowserTabsClient,
  destination: BrowserTabDestination,
): Promise<string | null> {
  if (readMirror().windows.length > 0) {
    return openInNewBrowserTabSync(client, destination);
  }
  // The mirror may not have seeded yet (a link that arrives during boot). Pull
  // the authoritative snapshot once; open only when a window exists afterwards.
  const server = await reseedMirror();
  if (primaryWindow(server ?? readMirror())) {
    return openInNewBrowserTabSync(client, destination);
  }
  return null;
}

/** What an inbound destination resolved to in the tab strip. */
export type InboundTabResolution = "focused" | "opened" | "unavailable";

/**
 * Focus the tab that already shows the destination, or open it in a new tab.
 * Resolves "unavailable" only when browser tabs have no window to open into, so
 * the caller can fall back to a plain navigation and the link is never dropped.
 */
export async function focusOrOpenBrowserTab(
  client: BrowserTabsClient,
  destination: BrowserTabDestination,
): Promise<InboundTabResolution> {
  if (focusExistingTab(destination)) return "focused";
  if (readMirror().windows.length > 0) {
    return (await openInNewBrowserTab(client, destination))
      ? "opened"
      : "unavailable";
  }
  await reseedMirror();
  if (focusExistingTab(destination)) return "focused";
  return (await openInNewBrowserTab(client, destination))
    ? "opened"
    : "unavailable";
}

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
