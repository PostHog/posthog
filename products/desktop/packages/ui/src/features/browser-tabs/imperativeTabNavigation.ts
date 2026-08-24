import { resolveServiceOptional } from "@posthog/di/container";
import {
  setTabTarget as setTabTargetLocal,
  type TabIdentity,
} from "@posthog/shared";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "./browserTabsClient";
import { pushTabHistoryEntry } from "./tabHistory";
import { applyLocalTransform, persistWrite, readMirror } from "./tabsSync";

export interface BrowserTabDestination extends TabIdentity {
  href: string;
  title?: string;
}

export type BrowserTabNavigationResult = "active" | "background" | "closed";

/** The tab attached to the current history entry, or null when tabs are off. */
export function getCurrentBrowserTabId(): string | null {
  return getRouterOrNull()?.history.location.state.tabId ?? null;
}

/**
 * Move one browser tab to a new route without stealing focus from another tab.
 * Active tabs use router history; background tabs update their durable target
 * and will load that route when the user returns.
 */
export function navigateBrowserTab(
  tabId: string | null,
  destination: BrowserTabDestination,
  navigateWithoutTabs: () => void,
): BrowserTabNavigationResult {
  if (!tabId) {
    navigateWithoutTabs();
    return "active";
  }

  const router = getRouterOrNull();
  if (router?.history.location.state.tabId === tabId) {
    pushTabHistoryEntry(router.history, destination.href, tabId);
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
    dashboardId: destination.dashboardId,
    taskId: destination.taskId,
    channelId: destination.channelId,
    channelSection: destination.channelSection,
    appView: destination.appView,
    activate: false,
  };

  applyLocalTransform((snapshot) =>
    setTabTargetLocal(snapshot, { ...target, now: Date.now }),
  );
  const client = resolveServiceOptional<BrowserTabsClient>(BROWSER_TABS_CLIENT);
  if (client) {
    void persistWrite(() => client.setTabTarget(target));
  }
  return "background";
}
