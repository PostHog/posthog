import {
  setTabTarget as setTabTargetLocal,
  type TabIdentity,
} from "@posthog/shared";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
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
