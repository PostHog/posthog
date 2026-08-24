import type { TabsSnapshot, TabViewState } from "@posthog/shared";

/** Where a tab is, plus the route-derived label/icon cache. */
interface TabLocationInput {
  href: string | null;
  viewState: TabViewState | null;
  dashboardId: string | null;
  taskId: string | null;
  channelId: string | null;
  channelSection?: string | null;
  appView?: string | null;
}

interface Subscriber<T> {
  onData: (data: T) => void;
  onError?: (error: unknown) => void;
}

/**
 * Renderer-facing facade over the host-router browserTabs procedures. Bound as
 * a passthrough in the renderer container; on web the same shape forwards over
 * HTTP. Mutations return the fresh snapshot, but windows also stay in sync via
 * onSnapshotChange, so callers can rely on the store rather than the return.
 */
export interface BrowserTabsClient {
  getSnapshot(): Promise<TabsSnapshot>;
  getPrimaryWindowId(): Promise<string>;
  openTab(
    input: TabLocationInput & {
      windowId: string;
      /** Renderer-minted id for the tab this call creates (local-first sync). */
      tabId?: string;
    },
  ): Promise<TabsSnapshot>;
  setTabTarget(
    input: TabLocationInput & { tabId: string },
  ): Promise<TabsSnapshot>;
  close(tabId: string): Promise<TabsSnapshot>;
  setActiveTab(input: {
    windowId: string;
    tabId: string | null;
  }): Promise<TabsSnapshot>;
  onSnapshotChange(sub: Subscriber<TabsSnapshot>): { unsubscribe: () => void };
}

export const BROWSER_TABS_CLIENT = Symbol.for("posthog.ui.BrowserTabsClient");
