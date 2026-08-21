import type { TabsSnapshot } from "@posthog/shared";

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
  openOrFocus(input: {
    windowId: string;
    dashboardId: string | null;
    taskId: string | null;
    channelId: string | null;
    channelSection?: string | null;
    appView?: string | null;
    /** Renderer-minted id for a tab this call may create (local-first sync). */
    tabId?: string;
  }): Promise<TabsSnapshot>;
  newBlankTab(input: {
    windowId: string;
    /** Renderer-minted id (see openOrFocus.tabId). */
    tabId?: string;
  }): Promise<TabsSnapshot>;
  setTabTarget(input: {
    tabId: string;
    dashboardId: string | null;
    taskId: string | null;
    channelId: string | null;
    channelSection?: string | null;
    appView?: string | null;
  }): Promise<TabsSnapshot>;
  close(tabId: string): Promise<TabsSnapshot>;
  setActiveTab(input: {
    windowId: string;
    tabId: string | null;
  }): Promise<TabsSnapshot>;
  onSnapshotChange(sub: Subscriber<TabsSnapshot>): { unsubscribe: () => void };
}

export const BROWSER_TABS_CLIENT = Symbol.for("posthog.ui.BrowserTabsClient");
